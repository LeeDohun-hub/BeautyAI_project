"""얼굴 크롭 + 피부영역 마스킹 전처리 (피부분석 A·C 개선).

기존 SkinAnalyzer는 원본 전체를 224로 리사이즈해 모델에 넣어 배경·머리카락·조명이
그대로 섞였다. 여기서 얼굴을 검출해 여유 패딩과 함께 크롭(A)하고, 크롭 안에서 피부
색 픽셀만 마스킹해 LAB a* 기반 홍조를 직접 측정(C)한다. 홍조는 학습 데이터가 거의
없어 회귀 모델 출력이 신뢰 불가라, 색상 기반 측정값으로 대체한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class FacePreprocessResult:
    # 모델 입력용 얼굴 크롭(RGB PIL). 얼굴 미검출 시 원본 전체.
    model_image: Image.Image
    # 얼굴이 실제로 검출됐는지(신뢰도 표기·폴백 판단용).
    face_detected: bool
    # 피부 픽셀 비율(0~1). 너무 낮으면 측정 신뢰도가 떨어진다.
    skin_ratio: float
    # 색상 기반 홍조 점수(0~100). 피부 픽셀이 없으면 None.
    redness: float | None


class FaceSkinPreprocessor:
    """haarcascade 얼굴 검출 + YCrCb/HSV 피부 마스크 + LAB a* 홍조 측정."""

    # 얼굴 박스를 이만큼 확장해 이마/턱/볼이 잘리지 않게 한다(학습 프레이밍에 근접).
    _PAD = 0.35

    def __init__(self) -> None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(cascade_path)

    def process(self, image_bytes: bytes) -> FacePreprocessResult:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        rgb = np.asarray(image)  # (H, W, 3) RGB uint8

        box = self._largest_face(rgb)
        if box is None:
            # 얼굴 미검출: 모델엔 원본을, 홍조는 전체 피부 마스크로 측정 시도.
            skin_ratio, redness = self._skin_redness(rgb)
            return FacePreprocessResult(
                model_image=image,
                face_detected=False,
                skin_ratio=skin_ratio,
                redness=redness,
            )

        x, y, w, h = box
        face_rgb = rgb[y : y + h, x : x + w]
        skin_ratio, redness = self._skin_redness(face_rgb)
        return FacePreprocessResult(
            model_image=Image.fromarray(face_rgb),
            face_detected=True,
            skin_ratio=skin_ratio,
            redness=redness,
        )

    def _largest_face(self, rgb: np.ndarray) -> tuple[int, int, int, int] | None:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        faces = self._cascade.detectMultiScale(
            gray, scaleFactor=1.08, minNeighbors=5, minSize=(48, 48)
        )
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
        # 여유 패딩을 더해 이미지 경계로 클램프.
        pad_w, pad_h = int(w * self._PAD), int(h * self._PAD)
        height, width = rgb.shape[:2]
        x0 = max(0, x - pad_w)
        y0 = max(0, y - pad_h)
        x1 = min(width, x + w + pad_w)
        y1 = min(height, y + h + pad_h)
        return x0, y0, x1 - x0, y1 - y0

    @staticmethod
    def _skin_mask(rgb: np.ndarray) -> np.ndarray:
        """YCrCb + HSV 교집합으로 피부 픽셀 마스크(bool)."""
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        ycrcb_mask = (cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127)

        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0]
        sat = hsv[:, :, 1]
        # 살구·붉은 계열 색조 + 최소 채도(순검정/순백 배경 제외).
        hsv_mask = ((hue <= 25) | (hue >= 172)) & (sat >= 30)
        return ycrcb_mask & hsv_mask

    def _skin_redness(self, rgb: np.ndarray) -> tuple[float, float | None]:
        if rgb.size == 0:
            return 0.0, None
        mask = self._skin_mask(rgb)
        total = mask.size
        skin_count = int(mask.sum())
        skin_ratio = skin_count / total if total else 0.0
        if skin_count < max(50, total * 0.01):
            return skin_ratio, None

        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        a = lab[:, :, 1].astype(np.float32)  # OpenCV 8bit: 128=중립, 클수록 붉음
        a_skin = a[mask]

        a_mean = float(a_skin.mean())
        # 국소 홍조(볼 붉음·염증)까지 반영: 강하게 붉은 피부 픽셀 비율.
        red_patch_ratio = float((a_skin >= 150).mean())

        # a* 평균 134(옅음)~162(뚜렷한 홍조)를 0~100으로 선형 매핑 + 국소 붉음 가산.
        base = (a_mean - 134.0) / (162.0 - 134.0) * 100.0
        redness = base * 0.8 + red_patch_ratio * 100.0 * 0.2
        redness = round(max(0.0, min(100.0, redness)), 1)
        return skin_ratio, redness


_preprocessor: FaceSkinPreprocessor | None = None


def get_face_skin_preprocessor() -> FaceSkinPreprocessor:
    global _preprocessor
    if _preprocessor is None:
        _preprocessor = FaceSkinPreprocessor()
    return _preprocessor
