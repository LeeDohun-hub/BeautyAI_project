"""2단 피부질환 모델 추론 (Tier1 선별 게이트 + Tier2 케어 분류).

RunPod에서 학습한 EfficientNet-B0 체크포인트(classes/arch 포함)를 로드해, 이미지 한 장을
클래스 확률 dict로 반환한다. 진단이 아니라 선별/안내 용도.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

_NORM_MEAN = [0.485, 0.456, 0.406]
_NORM_STD = [0.229, 0.224, 0.225]


class _TierModel:
    def __init__(self, model_path: str) -> None:
        self.model_path = Path(model_path)
        self.model: Any | None = None
        self.transform: Any | None = None
        self.torch: Any | None = None
        self.classes: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.model_path.exists()

    def load(self) -> bool:
        if self.model is not None:
            return True
        if not self.available:
            return False
        try:
            import torch
            from torchvision import models, transforms
        except ImportError:
            return False

        checkpoint = torch.load(self.model_path, map_location="cpu")
        classes = tuple(checkpoint.get("classes", ()))
        arch = checkpoint.get("arch", "efficientnet_b0")
        if arch == "mobilenet_v3_small":
            model = models.mobilenet_v3_small(weights=None)
            model.classifier[3] = torch.nn.Linear(model.classifier[3].in_features, len(classes))
        else:
            model = models.efficientnet_b0(weights=None)
            model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, len(classes))
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()

        self.torch = torch
        self.model = model
        self.classes = classes
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=_NORM_MEAN, std=_NORM_STD),
        ])
        return True

    def predict(self, image: Image.Image) -> dict[str, float] | None:
        if not self.load() or self.model is None or self.transform is None or self.torch is None:
            return None
        tensor = self.transform(image.convert("RGB")).unsqueeze(0)
        with self.torch.no_grad():
            probs = self.torch.softmax(self.model(tensor), dim=1).squeeze(0).tolist()
        return {cls: float(p) for cls, p in zip(self.classes, probs)}


class DermatologyModel:
    """Tier1 게이트 + Tier2 분류기 묶음."""

    def __init__(self, tier1_path: str, tier2_path: str) -> None:
        self.tier1 = _TierModel(tier1_path)
        self.tier2 = _TierModel(tier2_path)

    @property
    def available(self) -> bool:
        return self.tier1.available and self.tier2.available

    def predict_tier1(self, image: Image.Image) -> dict[str, float] | None:
        return self.tier1.predict(image)

    def predict_tier2(self, image: Image.Image) -> dict[str, float] | None:
        return self.tier2.predict(image)


_model: DermatologyModel | None = None


def get_dermatology_model() -> DermatologyModel:
    global _model
    if _model is None:
        from app.core.config import get_settings
        settings = get_settings()
        _model = DermatologyModel(
            settings.resolved_derma_tier1_model_path,
            settings.resolved_derma_tier2_model_path,
        )
    return _model
