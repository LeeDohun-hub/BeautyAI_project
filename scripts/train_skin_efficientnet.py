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

TARGETS = ("acne", "pore", "wrinkle", "redness", "pigmentation", "oiliness")


class SkinDataset(Dataset):
    def __init__(self, frame: pd.DataFrame, transform: transforms.Compose) -> None:
        self.frame = frame.reset_index(drop=True)
        self.transform = transform

    def __len__(self) -> int:
        return len(self.frame)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        row = self.frame.iloc[index]
        image = Image.open(row.image_path).convert("RGB")
        target = torch.tensor([row[target] for target in TARGETS], dtype=torch.float32)
        return self.transform(image), target


def build_model() -> nn.Module:
    model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(TARGETS))
    return model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifests/skin_multitask_manifest.csv")
    parser.add_argument("--out", default="data/models/skin_efficientnet_b0.pt")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--max-samples", type=int, default=0)
    args = parser.parse_args()

    frame = pd.read_csv(args.manifest)
    frame = frame[frame["image_path"].map(lambda value: Path(value).exists())]
    if args.max_samples and len(frame) > args.max_samples:
        frame = frame.sample(args.max_samples, random_state=42).reset_index(drop=True)
    if len(frame) < 20:
        raise SystemExit("Need at least 20 labeled images in the manifest.")

    train_frame, val_frame = train_test_split(frame, test_size=0.2, random_state=42)
    transform = transforms.Compose(
        [
            transforms.Resize((224, 224)),
            transforms.RandomHorizontalFlip(),
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

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    criterion = nn.SmoothL1Loss()
    train_loader = DataLoader(SkinDataset(train_frame, transform), batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(SkinDataset(val_frame, val_transform), batch_size=args.batch_size, shuffle=False, num_workers=0)

    best_val = float("inf")
    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        for images, targets in tqdm(train_loader, desc=f"epoch {epoch} train"):
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), targets)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(images)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for images, targets in tqdm(val_loader, desc=f"epoch {epoch} val"):
                images, targets = images.to(device), targets.to(device)
                val_loss += criterion(model(images), targets).item() * len(images)

        train_loss /= len(train_frame)
        val_loss /= len(val_frame)
        print(f"epoch={epoch} train_loss={train_loss:.4f} val_loss={val_loss:.4f}")
        if val_loss < best_val:
            best_val = val_loss
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "targets": TARGETS,
                    "val_loss": best_val,
                    "epochs": epoch,
                },
                out,
            )
            print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
