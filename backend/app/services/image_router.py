from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import cv2
import numpy as np
from PIL import Image


#: 검출된 얼굴이 사진에서 이 비율 이상이면 '얼굴 사진'으로 본다.
#:
#: 0.025 였다. 실측(얼굴 28장 / 바디 240장, 2026-08-18)에서 얼굴 사진 4장이 바디로
#: 샜는데 그중 3장이 0.009~0.022 로 **문턱 바로 아래**였다. 0.008 로 낮추면
#: 얼굴 정답이 24/28(85.7%) → 27/28(96.4%) 로 오르고 **바디는 239/240 그대로**다
#: (바디 오판 1건은 비율 0.553 이라 문턱과 무관하다).
#:
#: 남은 1장은 얼굴 자체가 검출되지 않아 문턱으로는 구제되지 않는다 — 그래서 화면의
#: 얼굴/바디 토글은 남겨 둔다.
#:
#: ⚠ 검증에 쓴 바디 사진은 전부 손발 접사다. 등·팔처럼 넓은 부위 사진은 표본에
#:   없었으므로, 그런 사진이 생기면 이 값을 다시 재는 게 맞다.
FACE_RATIO_THRESHOLD = 0.008


@dataclass(frozen=True)
class ImageRoute:
    analysis_mode: str
    reason: str
    face_count: int = 0
    largest_face_ratio: float = 0.0


class SkinImageRouter:
    def __init__(self) -> None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

    def route(self, image_bytes: bytes) -> ImageRoute:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        frame = np.asarray(image)
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(48, 48),
        )
        if len(faces) == 0:
            return ImageRoute(
                analysis_mode="body",
                reason="얼굴이 뚜렷하게 검출되지 않아 바디 피부 케어 분석으로 처리했습니다.",
            )

        image_area = max(1, frame.shape[0] * frame.shape[1])
        largest_face_ratio = max((w * h) / image_area for (_x, _y, w, h) in faces)
        if largest_face_ratio >= FACE_RATIO_THRESHOLD:
            return ImageRoute(
                analysis_mode="face",
                reason="얼굴 영역이 충분히 검출되어 얼굴 피부 케어 분석으로 처리했습니다.",
                face_count=len(faces),
                largest_face_ratio=round(largest_face_ratio, 4),
            )

        return ImageRoute(
            analysis_mode="body",
            reason="검출된 얼굴 영역이 작아 바디 피부 케어 분석으로 처리했습니다.",
            face_count=len(faces),
            largest_face_ratio=round(largest_face_ratio, 4),
        )


_router: SkinImageRouter | None = None


def get_skin_image_router() -> SkinImageRouter:
    global _router
    if _router is None:
        _router = SkinImageRouter()
    return _router

