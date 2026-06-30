from __future__ import annotations

import argparse
from pathlib import Path

import torch
from sklearn.model_selection import train_test_split
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms
from tqdm import tqdm

CLASSES = (
    "atopic_dermatitis",
    "contact_dermatitis",
    "eczema",
    "scabies",
    "seborrheic_dermatitis",
    "tinea_corporis",
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class BodySkinDataset(Dataset):
    def __init__(self, rows: list[tuple[Path, int]], transform: transforms.Compose) -> None:
        self.rows = rows
        self.transform = transform

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        from PIL import Image

        path, label = self.rows[index]
        with Image.open(path) as image:
            return self.transform(image.convert("RGB")), label


def collect_rows(root: Path) -> list[tuple[Path, int]]:
    rows: list[tuple[Path, int]] = []
    for label, class_name in enumerate(CLASSES):
        class_dir = root / class_name
        rows.extend(
            (path, label)
            for path in class_dir.rglob("*")
            if path.suffix.lower() in IMAGE_EXTENSIONS
        )
    return rows


def build_model() -> nn.Module:
    model = models.mobilenet_v3_small(
        weights=models.MobileNet_V3_Small_Weights.DEFAULT
    )
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(CLASSES))
    return model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default="data/datasets/skindisnet/preprocessed",
    )
    parser.add_argument(
        "--out",
        default="data/models/body_skin_mobilenet_v3.pt",
    )
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=3e-4)
    args = parser.parse_args()

    rows = collect_rows(Path(args.root))
    if len(rows) < 1000:
        raise SystemExit(f"Need prepared SkinDisNet images; found only {len(rows)}")
    labels = [label for _, label in rows]
    train_rows, val_rows = train_test_split(
        rows,
        test_size=0.2,
        random_state=42,
        stratify=labels,
    )
    train_transform = transforms.Compose(
        [
            transforms.Resize((224, 224)),
            transforms.RandomHorizontalFlip(),
            transforms.RandomRotation(8),
            transforms.ColorJitter(brightness=0.1, contrast=0.1),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ]
    )
    val_transform = transforms.Compose(
        [
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ]
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    class_counts = torch.bincount(
        torch.tensor([label for _, label in train_rows]),
        minlength=len(CLASSES),
    ).float()
    class_weights = class_counts.sum() / (len(CLASSES) * class_counts)
    criterion = nn.CrossEntropyLoss(weight=class_weights.to(device))
    train_loader = DataLoader(
        BodySkinDataset(train_rows, train_transform),
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=0,
    )
    val_loader = DataLoader(
        BodySkinDataset(val_rows, val_transform),
        batch_size=args.batch_size,
        num_workers=0,
    )

    best_accuracy = 0.0
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
        class_correct = [0] * len(CLASSES)
        class_total = [0] * len(CLASSES)
        with torch.no_grad():
            for images, targets in tqdm(val_loader, desc=f"epoch {epoch} val"):
                images, targets = images.to(device), targets.to(device)
                predictions = model(images).argmax(dim=1)
                correct += int((predictions == targets).sum())
                total += len(targets)
                for label in range(len(CLASSES)):
                    mask = targets == label
                    class_total[label] += int(mask.sum())
                    class_correct[label] += int(((predictions == targets) & mask).sum())
        accuracy = correct / max(1, total)
        print(f"epoch={epoch} val_accuracy={accuracy:.4f}")
        print(
            " ".join(
                f"{name}={class_correct[index] / max(1, class_total[index]):.3f}"
                for index, name in enumerate(CLASSES)
            )
        )
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "classes": CLASSES,
                    "val_accuracy": accuracy,
                    "epochs": epoch,
                },
                out,
            )
            print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
