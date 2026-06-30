from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image


DEFAULT_CLASSES = (
    "atopic_dermatitis",
    "contact_dermatitis",
    "eczema",
    "scabies",
    "seborrheic_dermatitis",
    "tinea_corporis",
)


class BodySkinClassifier:
    def __init__(self, model_path: str) -> None:
        self.model_path = Path(model_path)
        self.model: Any | None = None
        self.transform: Any | None = None
        self.torch: Any | None = None
        self.classes = DEFAULT_CLASSES

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
        classes = tuple(checkpoint.get("classes", DEFAULT_CLASSES))
        model = models.mobilenet_v3_small(weights=None)
        model.classifier[3] = torch.nn.Linear(model.classifier[3].in_features, len(classes))
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()

        self.torch = torch
        self.model = model
        self.classes = classes
        self.transform = transforms.Compose(
            [
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406],
                    std=[0.229, 0.224, 0.225],
                ),
            ]
        )
        return True

    def predict(self, image: Image.Image) -> list[tuple[str, float]] | None:
        if not self.load() or self.model is None or self.transform is None or self.torch is None:
            return None
        tensor = self.transform(image.convert("RGB")).unsqueeze(0)
        with self.torch.no_grad():
            logits = self.model(tensor)
            probabilities = self.torch.softmax(logits / 2.0, dim=1).squeeze(0)
        values = probabilities.detach().cpu().tolist()
        return sorted(
            (
                (label, round(min(99.0, float(value) * 100.0), 1))
                for label, value in zip(self.classes, values)
            ),
            key=lambda item: item[1],
            reverse=True,
        )
