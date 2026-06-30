from __future__ import annotations

import argparse
from pathlib import Path

import torch
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader
from torchvision import models, transforms

from train_body_skin_model import BodySkinDataset, CLASSES, collect_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default="data/datasets/skindisnet/preprocessed",
    )
    parser.add_argument(
        "--model",
        default="data/models/body_skin_mobilenet_v3.pt",
    )
    args = parser.parse_args()

    rows = collect_rows(Path(args.root))
    labels = [label for _, label in rows]
    _, val_rows = train_test_split(
        rows,
        test_size=0.2,
        random_state=42,
        stratify=labels,
    )
    transform = transforms.Compose(
        [
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ]
    )
    checkpoint = torch.load(args.model, map_location="cpu")
    model = models.mobilenet_v3_small(weights=None)
    model.classifier[3] = torch.nn.Linear(model.classifier[3].in_features, len(CLASSES))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    class_correct = [0] * len(CLASSES)
    class_total = [0] * len(CLASSES)
    with torch.no_grad():
        for images, targets in DataLoader(
            BodySkinDataset(val_rows, transform),
            batch_size=16,
            num_workers=0,
        ):
            predictions = model(images).argmax(dim=1)
            for label in range(len(CLASSES)):
                mask = targets == label
                class_total[label] += int(mask.sum())
                class_correct[label] += int(((predictions == targets) & mask).sum())

    total_correct = sum(class_correct)
    total = sum(class_total)
    print(f"overall={total_correct / total:.4f} ({total_correct}/{total})")
    for index, name in enumerate(CLASSES):
        print(
            f"{name}={class_correct[index] / max(1, class_total[index]):.4f} "
            f"({class_correct[index]}/{class_total[index]})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
