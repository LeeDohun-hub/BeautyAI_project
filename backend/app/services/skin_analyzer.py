from io import BytesIO

import numpy as np
from PIL import Image, ImageStat

from app.ai.skin_model import EfficientNetSkinRegressor
from app.core.config import get_settings
from app.schemas.api import SkinScores


class SkinAnalyzer:
    """Replace this service with an EfficientNet/PyTorch model when weights are ready."""

    def analyze(self, image_bytes: bytes) -> SkinScores:
        image = Image.open(BytesIO(image_bytes)).convert("RGB").resize((224, 224))
        model_scores = EfficientNetSkinRegressor(get_settings().resolved_skin_model_path).predict(image)
        if model_scores:
            return SkinScores(**model_scores)

        stat = ImageStat.Stat(image)
        mean_r, mean_g, mean_b = stat.mean
        arr = np.asarray(image).astype(np.float32)
        luminance = arr.mean(axis=2)
        texture = float(np.std(luminance))
        redness_signal = max(0.0, mean_r - ((mean_g + mean_b) / 2))
        saturation = float(np.std(arr, axis=2).mean())
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
    labels = ", ".join(f"{name} {score:.0f}" for name, score in top)
    return f"Primary care priorities: {labels}."
