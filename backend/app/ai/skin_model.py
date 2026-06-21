from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

TARGETS = ("acne", "pore", "wrinkle", "redness", "pigmentation", "oiliness")


class EfficientNetSkinRegressor:
    def __init__(self, model_path: str) -> None:
        self.model_path = Path(model_path)
        self.model: Any | None = None
        self.transform: Any | None = None
        self.torch: Any | None = None

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
        model = models.efficientnet_b0(weights=None)
        model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, len(TARGETS))
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()

        self.torch = torch
        self.model = model
        self.transform = transforms.Compose(
            [
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ]
        )
        return True

    def predict(self, image: Image.Image) -> dict[str, float] | None:
        if not self.load() or self.model is None or self.transform is None or self.torch is None:
            return None
        tensor = self.transform(image.convert("RGB")).unsqueeze(0)
        with self.torch.no_grad():
            raw = self.model(tensor).squeeze(0).detach().cpu().tolist()
        scores = [max(0.0, min(100.0, float(score))) for score in raw]
        return {target: round(float(score), 1) for target, score in zip(TARGETS, scores)}
