"""퍼스널컬러 4계절(봄/여름/가을/겨울) EfficientNet 분류기 학습.

입력: prepare_personal_color_dataset.py 가 만든 manifest (image_path, season, partition).
출력: data/models/personal_color_efficientnet.pt  (app.ai.personal_color_model 이 로드)

계절만 학습한다(웜/쿨 결정). subtype은 추론 시 WB 보정 지표로 계산한다.
모델 파일이 생기면 personal_color_analyzer 가 자동으로 모델을 쓰고, 없으면 휴리스틱+WB로 폴백한다.

사용:
    cd backend
    uv pip install -r requirements-train.txt --python .venv\\Scripts\\python.exe
    cd ..
    backend\\.venv\\Scripts\\python.exe scripts\\train_personal_color_efficientnet.py --epochs 15
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import torch
from PIL import Image
from sklearn.model_selection import train_test_split
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms
from tqdm import tqdm

SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_INDEX = {season: index for index, season in enumerate(SEASONS)}


class SeasonDataset(Dataset):
    def __init__(self, frame: pd.DataFrame, transform: transforms.Compose) -> None:
        self.frame = frame.reset_index(drop=True)
        self.transform = transform

    def __len__(self) -> int:
        return len(self.frame)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        row = self.frame.iloc[index]
        image = Image.open(row.image_path).convert("RGB")
        return self.transform(image), SEASON_INDEX[row.season]


def build_model() -> nn.Module:
    model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(SEASONS))
    return model


def split_frames(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    # manifest 에 train/validation 파티션이 있으면 그대로 쓰고, 없으면 랜덤 분할.
    partitions = set(frame.get("partition", pd.Series(dtype=str)).astype(str))
    if {"train"} & partitions and ({"validation", "val", "test"} & partitions):
        train = frame[frame.partition.astype(str).str.lower() == "train"]
        val = frame[frame.partition.astype(str).str.lower().isin(["validation", "val", "test"])]
        if len(train) >= 20 and len(val) >= 8:
            return train, val
    return train_test_split(frame, test_size=0.2, random_state=42, stratify=frame.season)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifests/personal_color_manifest.csv")
    parser.add_argument("--out", default="data/models/personal_color_efficientnet.pt")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--max-samples", type=int, default=0)
    args = parser.parse_args()

    frame = pd.read_csv(args.manifest)
    frame = frame[frame["image_path"].map(lambda value: Path(value).exists())]
    frame = frame[frame["season"].isin(SEASONS)]
    if args.max_samples and len(frame) > args.max_samples:
        frame = frame.sample(args.max_samples, random_state=42).reset_index(drop=True)
    if len(frame) < 40:
        raise SystemExit("manifest 에 최소 40장 이상의 라벨 이미지가 필요합니다.")

    train_frame, val_frame = split_frames(frame)

    train_transform = transforms.Compose(
        [
            transforms.Resize((224, 224)),
            transforms.RandomHorizontalFlip(),
            transforms.ColorJitter(brightness=0.1, contrast=0.1),  # 조명 변동에 강건하게
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )
    val_transform = transforms.Compose(
        [
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )

    # 계절 불균형 보정 가중치.
    counts = train_frame.season.value_counts().to_dict()
    weights = torch.tensor(
        [1.0 / max(1, counts.get(season, 0)) for season in SEASONS], dtype=torch.float32
    )
    weights = weights / weights.sum() * len(SEASONS)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    criterion = nn.CrossEntropyLoss(weight=weights.to(device))
    train_loader = DataLoader(SeasonDataset(train_frame, train_transform), batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(SeasonDataset(val_frame, val_transform), batch_size=args.batch_size, shuffle=False, num_workers=0)

    best_acc = 0.0
    for epoch in range(1, args.epochs + 1):
        model.train()
        for images, targets in tqdm(train_loader, desc=f"epoch {epoch} train"):
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), targets)
            loss.backward()
            optimizer.step()

        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for images, targets in tqdm(val_loader, desc=f"epoch {epoch} val"):
                images, targets = images.to(device), targets.to(device)
                preds = model(images).argmax(dim=1)
                correct += int((preds.cpu() == targets.cpu()).sum())
                total += len(targets)

        acc = correct / max(1, total)
        print(f"epoch={epoch} val_acc={acc:.4f}")
        if acc > best_acc:
            best_acc = acc
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "seasons": SEASONS,
                    "val_acc": best_acc,
                    "epochs": epoch,
                },
                out,
            )
            print(f"saved {out} (val_acc={best_acc:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
