from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image

from app.ai.skin_model import EfficientNetSkinRegressor
from app.core.config import get_settings
from app.schemas.api import SkinScores


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
    def analyze(self, image_bytes: bytes) -> SkinScores:
        image = Image.open(BytesIO(image_bytes)).convert("RGB").resize((224, 224))

        model_scores = _get_regressor().predict(image)
        if model_scores:
            return SkinScores(**model_scores)

        # NumPy-based fallback: all pixel math vectorized
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

        return SkinScores(
            acne=self._clamp(redness_signal * 1.6 + saturation * 0.25),
            pore=self._clamp(texture * 1.4),
            wrinkle=self._clamp(texture * 0.75 + dark_ratio * 55),
            redness=self._clamp(redness_signal * 2.2),
            pigmentation=self._clamp(dark_ratio * 100 + saturation * 0.35),
            oiliness=self._clamp(bright_ratio * 85 + max(0.0, mean_r + mean_g - 260) * 0.18),
        )

    @staticmethod
    def _clamp(value: float) -> float:
        return round(max(0.0, min(100.0, value)), 1)


def summarize_scores(scores: SkinScores) -> str:
    values = scores.model_dump()
    top = sorted(values.items(), key=lambda item: item[1], reverse=True)[:2]
    labels = ", ".join(f"{TARGET_LABELS[name]} {score:.0f}" for name, score in top)
    return f"우선 관리가 필요한 항목은 {labels}입니다."
