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
        self.label_scale: float = 1.0

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
        # Models trained on normalized 0-1 labels store label_scale=100 to map back
        # to the 0-100 score range. Older models default to 1.0 (already 0-100).
        self.label_scale = float(checkpoint.get("label_scale", 1.0))

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
        # TTA(test-time augmentation): 원본 + 좌우반전 + 밝기(±)로 4번 채점해 평균한다.
        # 한 장짜리 예측의 조명/프레이밍 민감도(같은 얼굴에도 점수가 흔들리는 문제)를 낮춘다.
        # 프론트의 '여러 장 평균'과 곱해져 재현성이 더 안정된다. 라벨이 거칠어(2~3단계)
        # 정밀도엔 한계가 있으므로 화면은 3구간(양호/보통/관리필요)으로 표시한다(프론트).
        from PIL import ImageEnhance, ImageOps

        base = image.convert("RGB")
        variants = [
            base,
            ImageOps.mirror(base),
            ImageEnhance.Brightness(base).enhance(0.9),
            ImageEnhance.Brightness(base).enhance(1.1),
        ]
        batch = self.torch.stack([self.transform(v) for v in variants])
        with self.torch.no_grad():
            raw = self.model(batch).mean(dim=0).detach().cpu().tolist()
        scores = [max(0.0, min(100.0, float(score) * self.label_scale)) for score in raw]
        return {target: round(float(score), 1) for target, score in zip(TARGETS, scores)}
