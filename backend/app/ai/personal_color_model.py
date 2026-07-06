from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

# 모델이 예측하는 4계절(퍼스널컬러의 웜/쿨 축을 결정하는 주관적 부분).
SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_TONE = {"spring": "warm", "autumn": "warm", "summer": "cool", "winter": "cool"}


class EfficientNetSeasonClassifier:
    """Deep Armocromia 등으로 학습한 4계절 분류기. 모델 파일이 없으면 비활성(→휴리스틱 폴백)."""

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
        model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, len(SEASONS))
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

    def predict(self, image: Image.Image) -> tuple[str, float] | None:
        """(계절, 신뢰도) 또는 None. 신뢰도는 softmax 최대 확률."""
        probs = self.predict_probs(image)
        if probs is None:
            return None
        season = max(probs, key=probs.get)
        return season, probs[season]

    def predict_probs(self, image: Image.Image, *, tta: bool = True) -> dict[str, float] | None:
        """계절별 softmax 확률 dict 또는 None. 여러 장 평균(앙상블)용으로 전체 분포를 반환한다.

        tta=True 이면 원본 + 수평 뒤집기의 softmax를 평균한다(test-time augmentation).
        얼굴은 좌우 대칭이라 flip 은 라벨을 바꾸지 않으면서 예측을 안정화한다.
        """
        if not self.load() or self.model is None or self.transform is None or self.torch is None:
            return None
        rgb = image.convert("RGB")
        views = [rgb]
        if tta:
            views.append(rgb.transpose(Image.FLIP_LEFT_RIGHT))
        with self.torch.no_grad():
            batch = self.torch.stack([self.transform(view) for view in views])
            logits = self.model(batch)
            probs = self.torch.softmax(logits, dim=1).mean(dim=0)
        return {season: float(probs[i]) for i, season in enumerate(SEASONS)}
