from __future__ import annotations

import numpy as np

from app.ai.skin_model import EfficientNetSkinRegressor
from app.core.config import get_settings
from app.schemas.api import SkinScores
from app.services.face_skin_preprocess import get_face_skin_preprocessor


TARGET_LABELS = {
    "acne": "트러블",
    "pore": "모공",
    "wrinkle": "주름",
    "redness": "홍조",
    "pigmentation": "색소침착",
    "oiliness": "유분",
}

# Singleton model — loaded once at first use, reused across all requests
_regressor: EfficientNetSkinRegressor | None = None


def _get_regressor() -> EfficientNetSkinRegressor:
    global _regressor
    if _regressor is None:
        _regressor = EfficientNetSkinRegressor(get_settings().resolved_skin_model_path)
    return _regressor


class SkinAnalyzer:
    def analyze(self, image_bytes: bytes) -> tuple[SkinScores, str]:
        # A: 얼굴을 검출해 크롭(배경·머리카락 제거) + C용 피부영역/홍조 측정.
        pre = get_face_skin_preprocessor().process(image_bytes)
        image = pre.model_image.convert("RGB").resize((224, 224))

        model_scores = _get_regressor().predict(image)
        if model_scores:
            scores_map = model_scores
        else:
            scores_map = self._heuristic_scores(image)

        # C: 홍조는 학습 데이터가 거의 없어 회귀 모델 출력이 신뢰 불가 → 피부 색상(LAB a*)
        # 기반 측정값으로 대체한다. 측정 실패(피부 픽셀 부족) 시에만 모델값을 유지.
        redness_from_color = pre.redness is not None
        if redness_from_color:
            scores_map = {**scores_map, "redness": float(pre.redness)}

        scores = SkinScores(**scores_map)
        note = self._confidence_note(pre.face_detected, pre.skin_ratio, redness_from_color)
        return scores, note

    def _heuristic_scores(self, image) -> dict[str, float]:
        # NumPy-based fallback: all pixel math vectorized (모델 미탑재 환경 대비)
        arr = np.asarray(image, dtype=np.float32)          # (224, 224, 3)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

        mean_r, mean_g, mean_b = r.mean(), g.mean(), b.mean()
        luminance = (r + g + b) / 3.0
        texture = float(luminance.std())
        redness_signal = float(max(0.0, mean_r - (mean_g + mean_b) / 2))

        pixel_mean = luminance[:, :, np.newaxis]            # broadcast-friendly
        saturation = float(np.sqrt(((arr - pixel_mean) ** 2).mean(axis=2)).mean())

        dark_ratio = float((luminance < 80).mean())
        bright_ratio = float((luminance > 190).mean())

        return {
            "acne": self._clamp(redness_signal * 1.6 + saturation * 0.25),
            "pore": self._clamp(texture * 1.4),
            "wrinkle": self._clamp(texture * 0.75 + dark_ratio * 55),
            "redness": self._clamp(redness_signal * 2.2),
            "pigmentation": self._clamp(dark_ratio * 100 + saturation * 0.35),
            "oiliness": self._clamp(bright_ratio * 85 + max(0.0, mean_r + mean_g - 260) * 0.18),
        }

    @staticmethod
    def _confidence_note(face_detected: bool, skin_ratio: float, redness_from_color: bool) -> str:
        parts = ["피부 점수는 사진 기반 참고용 추정치입니다."]
        if redness_from_color:
            parts.append("홍조는 피부 색상(LAB)에서 직접 측정했습니다.")
        if not face_detected:
            parts.append("얼굴이 뚜렷하게 검출되지 않아 정확도가 낮을 수 있어요. 밝은 곳에서 정면 사진을 권장합니다.")
        elif skin_ratio < 0.15:
            parts.append("피부 영역이 좁게 잡혀 정확도가 낮을 수 있어요. 얼굴이 크게 나온 정면 사진을 권장합니다.")
        return " ".join(parts)

    @staticmethod
    def _clamp(value: float) -> float:
        return round(max(0.0, min(100.0, value)), 1)


def summarize_scores(scores: SkinScores) -> str:
    values = scores.model_dump()
    top = sorted(values.items(), key=lambda item: item[1], reverse=True)[:2]
    labels = ", ".join(f"{TARGET_LABELS[name]} {score:.0f}" for name, score in top)
    return f"우선 관리가 필요한 항목은 {labels}입니다."
