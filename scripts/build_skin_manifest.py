from __future__ import annotations

import argparse
import csv
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
TARGETS = ("acne", "pore", "wrinkle", "redness", "pigmentation", "oiliness")

KEYWORDS = {
    "acne": ("acne", "pimple", "blemish"),
    "pore": ("pore", "pores"),
    "wrinkle": ("wrinkle", "wrinkles", "aging", "ageing"),
    "redness": ("redness", "red", "sensitive", "irritation"),
    "pigmentation": ("pigmentation", "pigment", "spot", "spots", "dark", "melasma"),
    "oiliness": ("oily", "oiliness", "sebum"),
}


def score_from_path(path: Path) -> dict[str, float]:
    text = " ".join(part.lower() for part in path.parts)
    scores = {target: 0.0 for target in TARGETS}
    for target, words in KEYWORDS.items():
        if any(word in text for word in words):
            scores[target] = 85.0
    if "normal" in text or "clear" in text:
        return {target: 10.0 for target in TARGETS}
    if "mild" in text:
        scores = {target: (35.0 if value else 5.0) for target, value in scores.items()}
    if "moderate" in text:
        scores = {target: (60.0 if value else 8.0) for target, value in scores.items()}
    if "severe" in text:
        scores = {target: (90.0 if value else 10.0) for target, value in scores.items()}
    return scores


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/datasets/kaggle")
    parser.add_argument("--out", default="data/manifests/skin_multitask_manifest.csv")
    args = parser.parse_args()

    root = Path(args.root)
    rows = []
    for image_path in root.rglob("*"):
        if image_path.suffix.lower() not in IMAGE_EXTS:
            continue
        scores = score_from_path(image_path.relative_to(root))
        if not any(scores.values()):
            continue
        rows.append({"image_path": str(image_path), **scores})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["image_path", *TARGETS])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

