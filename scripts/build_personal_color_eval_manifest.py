"""Build an expert-eval manifest from labeled folders.

Expected folder layout:

    data/eval/holdout/
      spring/
      summer/
      autumn/
      winter/

Usage:
    python scripts/build_personal_color_eval_manifest.py \
        --root data/eval/holdout \
        --out data/eval/personal_color_eval_manifest.csv
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

SEASONS = ("spring", "summer", "autumn", "winter")
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build personal color eval manifest from season folders.")
    parser.add_argument("--root", default="data/eval/holdout")
    parser.add_argument("--out", default="data/eval/personal_color_eval_manifest.csv")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"eval root not found: {root}")

    rows: list[tuple[str, str]] = []
    counts: Counter[str] = Counter()
    for season in SEASONS:
        folder = root / season
        if not folder.exists():
            continue
        for image_path in sorted(folder.rglob("*")):
            if image_path.is_file() and image_path.suffix.lower() in EXTENSIONS:
                rows.append((str(image_path), season))
                counts[season] += 1

    if not rows:
        raise SystemExit(f"no images found under {root}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["image_path", "label"])
        writer.writerows(rows)

    print(f"manifest saved: {out} rows={len(rows)}")
    print("season counts:", dict(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
