"""Create face-cropped training images for the personal color classifier.

The app now predicts personal color from a face-centered crop, so the training
set should use the same input domain. This script reads an existing manifest
(`image_path,season,partition`), runs the production crop logic, saves cropped
images, and writes a new manifest that can be passed to
train_personal_color_efficientnet.py.

Usage:
    python scripts/prepare_personal_color_face_crops.py \
        --manifest data/manifests/personal_color_manifest.csv \
        --out-root data/datasets/personal_color_face_crops \
        --out data/manifests/personal_color_face_crop_manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import Counter
from pathlib import Path

from PIL import Image
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.personal_color_analyzer import PersonalColorAnalyzer  # noqa: E402


def _safe_stem(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:10]
    return f"{path.stem}_{digest}"


def _write_rgb(path: Path, rgb) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb.astype("uint8")).save(path, quality=95)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build face-cropped personal color training manifest.")
    parser.add_argument("--manifest", default="data/manifests/personal_color_manifest.csv")
    parser.add_argument("--out-root", default="data/datasets/personal_color_face_crops")
    parser.add_argument("--out", default="data/manifests/personal_color_face_crop_manifest.csv")
    parser.add_argument("--include-uncropped", action="store_true", help="Keep images when face crop fails.")
    parser.add_argument("--limit", type=int, default=0, help="Optional debug limit.")
    args = parser.parse_args()

    manifest = Path(args.manifest)
    out_root = Path(args.out_root)
    out = Path(args.out)
    if not manifest.exists():
        raise SystemExit(f"manifest not found: {manifest}")

    analyzer = PersonalColorAnalyzer()
    rows: list[tuple[str, str, str]] = []
    counts: Counter[str] = Counter()
    partitions: Counter[str] = Counter()
    cropped = 0
    skipped = 0
    missing = 0

    with manifest.open(encoding="utf-8-sig", newline="") as file:
        reader = list(csv.DictReader(file))

    if args.limit:
        reader = reader[: args.limit]

    for row in tqdm(reader, desc="face crops"):
        src = Path(row["image_path"])
        season = row["season"]
        partition = (row.get("partition") or "train").strip().lower() or "train"
        if not src.exists():
            missing += 1
            continue

        try:
            rgb = analyzer._load_rgb(src.read_bytes())
            crop_rgb, face_detected = analyzer._face_crop(rgb)
        except Exception:
            skipped += 1
            continue

        if not face_detected and not args.include_uncropped:
            skipped += 1
            continue

        if face_detected:
            cropped += 1
        dest = out_root / partition / season / f"{_safe_stem(src)}.jpg"
        _write_rgb(dest, crop_rgb)
        rows.append((str(dest), season, partition))
        counts[season] += 1
        partitions[partition] += 1

    if not rows:
        raise SystemExit("no face crop images were written")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["image_path", "season", "partition"])
        writer.writerows(rows)

    print(f"manifest saved: {out} rows={len(rows)}")
    print(f"cropped={cropped} skipped={skipped} missing={missing}")
    print("seasons:", dict(counts))
    print("partitions:", dict(partitions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
