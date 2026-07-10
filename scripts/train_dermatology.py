"""통합 매니페스트로 2단 피부 모델 학습 (Tier1 선별 게이트 / Tier2 질환분류).

Tier1은 악성 조기발견이 목적이라, 전체 정확도가 아니라 **urgent_referral(악성) recall**을
1순위로 best 체크포인트를 고른다(흑색종을 놓치는 게 가장 치명적).

RunPod 실행 예:
    python scripts/train_dermatology.py --tier 1 \
      --manifest data/manifests/dermatology_manifest.csv \
      --out data/models/derma_tier1_gate.pt --epochs 15 --batch-size 32

    python scripts/train_dermatology.py --tier 2 \
      --manifest data/manifests/dermatology_manifest.csv \
      --out data/models/derma_tier2_classifier.pt --epochs 20 --batch-size 32
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

from dermatology_taxonomy import TIER1, TIER2

URGENT = "urgent_referral"


class ManifestDataset(Dataset):
    def __init__(self, frame: pd.DataFrame, classes: list[str], transform: transforms.Compose) -> None:
        self.frame = frame.reset_index(drop=True)
        self.class_to_idx = {name: i for i, name in enumerate(classes)}
        self.transform = transform

    def __len__(self) -> int:
        return len(self.frame)

    def __getitem__(self, index: int):
        row = self.frame.iloc[index]
        with Image.open(row.image_path) as image:
            tensor = self.transform(image.convert("RGB"))
        return tensor, self.class_to_idx[row.label]


def build_model(arch: str, num_classes: int) -> nn.Module:
    if arch == "efficientnet_b0":
        model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
        model.classifier[1] = nn.Linear(model.classifier[1].in_features, num_classes)
    elif arch == "mobilenet_v3_small":
        model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
        model.classifier[3] = nn.Linear(model.classifier[3].in_features, num_classes)
    else:
        raise SystemExit(f"unknown arch: {arch}")
    return model


def load_frame(manifest: Path, tier: int) -> tuple[pd.DataFrame, list[str]]:
    label_col = "tier1" if tier == 1 else "tier2"
    allowed = list(TIER1) if tier == 1 else list(TIER2)
    frame = pd.read_csv(manifest)
    frame = frame[frame[label_col].notna() & (frame[label_col].astype(str).str.len() > 0)].copy()
    frame["label"] = frame[label_col].astype(str)
    frame = frame[frame["label"].isin(allowed)]
    frame = frame[frame["image_path"].map(lambda v: Path(v).exists())]
    present = [c for c in allowed if c in set(frame["label"])]
    if len(frame) < 100 or len(present) < 2:
        raise SystemExit(f"tier{tier}: 유효 표본 부족 (rows={len(frame)}, classes={present})")
    return frame, present


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=int, choices=(1, 2), required=True)
    parser.add_argument("--manifest", default="data/manifests/dermatology_manifest.csv")
    parser.add_argument("--out", default="")
    parser.add_argument("--arch", default="efficientnet_b0",
                        choices=("efficientnet_b0", "mobilenet_v3_small"))
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=3e-4)
    args = parser.parse_args()

    out = Path(args.out or f"data/models/derma_tier{args.tier}.pt")
    frame, classes = load_frame(Path(args.manifest), args.tier)
    print(f"tier{args.tier}: {len(frame)} images, classes={classes}")

    train_frame, val_frame = train_test_split(
        frame, test_size=0.2, random_state=42, stratify=frame["label"]
    )
    train_tf = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(10),
        transforms.ColorJitter(brightness=0.1, contrast=0.1),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    val_tf = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(args.arch, len(classes)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)

    counts = train_frame["label"].value_counts()
    weights = torch.tensor(
        [counts.sum() / (len(classes) * counts.get(name, 1)) for name in classes],
        dtype=torch.float32,
    )
    criterion = nn.CrossEntropyLoss(weight=weights.to(device), label_smoothing=0.05)

    train_loader = DataLoader(ManifestDataset(train_frame, classes, train_tf),
                              batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(ManifestDataset(val_frame, classes, val_tf),
                            batch_size=args.batch_size, num_workers=0)
    urgent_idx = classes.index(URGENT) if URGENT in classes else None

    best_key = -1.0
    for epoch in range(1, args.epochs + 1):
        model.train()
        for images, targets in tqdm(train_loader, desc=f"epoch {epoch} train"):
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), targets)
            loss.backward()
            optimizer.step()

        model.eval()
        correct = total = 0
        class_correct = [0] * len(classes)
        class_total = [0] * len(classes)
        with torch.no_grad():
            for images, targets in tqdm(val_loader, desc=f"epoch {epoch} val"):
                images, targets = images.to(device), targets.to(device)
                preds = model(images).argmax(dim=1)
                correct += int((preds == targets).sum())
                total += len(targets)
                for c in range(len(classes)):
                    mask = targets == c
                    class_total[c] += int(mask.sum())
                    class_correct[c] += int(((preds == targets) & mask).sum())
        accuracy = correct / max(1, total)
        recalls = {classes[c]: class_correct[c] / max(1, class_total[c]) for c in range(len(classes))}
        urgent_recall = recalls.get(URGENT, 0.0)
        print(f"epoch={epoch} val_acc={accuracy:.4f} " +
              " ".join(f"{k}={v:.3f}" for k, v in recalls.items()))

        # Tier1: urgent recall 1순위(+전체정확도 보조)로 best 선정. Tier2: 전체정확도.
        key = (urgent_recall * 100 + accuracy) if args.tier == 1 else accuracy
        if key > best_key:
            best_key = key
            out.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "model_state_dict": model.state_dict(),
                "classes": tuple(classes),
                "tier": args.tier,
                "arch": args.arch,
                "val_accuracy": accuracy,
                "urgent_recall": urgent_recall,
                "epochs": epoch,
            }, out)
            print(f"saved {out} (acc={accuracy:.4f}, urgent_recall={urgent_recall:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
