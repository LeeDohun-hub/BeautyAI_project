"""Deep Armocromia annotations.csv → 퍼스널컬러 계절 학습 manifest.

Deep Armocromia(github.com/lorenzo-stacchio/Deep-Armocromia)는 폼 작성 후 Google Drive에서
받고, 내부 zip(ORIGINAL_RGB_NOT_PROCESSED.zip / RGB-M.zip / BM.zip)은 비밀번호로 풀어야 한다.

주의: annotations.csv의 경로(`RGB/train/.../10306.jpg`)는 실제 압축 폴더명·확장자와 다르다.
실제 원본은 `ORIGINAL_RGB_NOT_PROCESSED/<partition>/<class>/<sub_class>/<id>.png` 형태다.
그래서 annotations 는 (partition, class, sub_class, 파일 stem)만 신뢰하고, --image-root 아래에서
확장자(png/jpg)를 유연하게 찾아 매칭한다.

계절(class)만 학습 타깃으로 쓴다 — 웜/쿨은 계절이 결정하고(봄·가을=웜, 여름·겨울=쿨),
subtype(밝기/선명도)은 추론 시 WB 보정 지표로 계산한다(personal_color_analyzer 참고).

사용:
    # 원본 RGB (ORIGINAL_RGB_NOT_PROCESSED 압축해제 폴더)로:
    python scripts/prepare_personal_color_dataset.py \
        --annotations "data/release/annotations.csv" \
        --image-root  "data/.../ORIGINAL_RGB_NOT_PROCESSED"
    # 마스킹 얼굴본(RGB-M)으로:
    python scripts/prepare_personal_color_dataset.py \
        --annotations "data/release/annotations.csv" --image-root "data/release/RGB-M"
출력:
    data/manifests/personal_color_manifest.csv  (image_path, season, partition)
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

SEASON_MAP = {
    "primavera": "spring", "spring": "spring",
    "estate": "summer", "summer": "summer",
    "autunno": "autumn", "autumn": "autumn", "fall": "autumn",
    "inverno": "winter", "winter": "winter",
}
_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def resolve_image(image_root: Path, row: dict, path_field: str) -> Path | None:
    rel = str(row.get(path_field) or row.get("path_rgb_original") or "").strip().replace("\\", "/").lstrip("/")

    # 1) annotations 경로 그대로 시도.
    if rel and (image_root / rel).exists():
        return image_root / rel

    # 2) (partition/class/sub_class + 파일 stem)으로 재구성 + 확장자 유연 매칭.
    partition = str(row.get("partition", "")).strip()
    cls = str(row.get("class", "")).strip()
    sub = str(row.get("sub_class", "")).strip()
    stem = Path(rel).stem if rel else ""
    if partition and cls and sub and stem:
        base = image_root / partition / cls / sub / stem
        for ext in _EXTS:
            if base.with_suffix(ext).exists():
                return base.with_suffix(ext)

    # 3) 앞 폴더명(RGB 등) 무시하고 tail + 확장자 유연.
    if rel and "/" in rel:
        tail = Path("/".join(rel.split("/")[1:]))
        for ext in _EXTS:
            cand = image_root / tail.with_suffix(ext)
            if cand.exists():
                return cand
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Deep Armocromia → 퍼스널컬러 계절 manifest")
    parser.add_argument("--annotations", required=True, help="annotations.csv 경로")
    parser.add_argument("--image-root", required=True, help="이미지 루트(partition 폴더 test/train/validation 를 직접 포함하는 폴더)")
    parser.add_argument("--path-field", default="path_rgb_original", help="경로 컬럼(마스킹본이면 path_rgb_masked)")
    parser.add_argument("--out", default="data/manifests/personal_color_manifest.csv")
    args = parser.parse_args()

    annotations = Path(args.annotations)
    image_root = Path(args.image_root)
    if not annotations.exists():
        raise SystemExit(f"annotations.csv 를 찾을 수 없습니다: {annotations}")
    if not image_root.exists():
        raise SystemExit(f"image-root 폴더가 없습니다: {image_root}")

    rows: list[tuple[str, str, str]] = []
    counts: Counter[str] = Counter()
    missing = 0
    with annotations.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            season = SEASON_MAP.get(str(row.get("class", "")).strip().lower())
            if not season:
                continue
            image = resolve_image(image_root, row, args.path_field)
            if image is None:
                missing += 1
                continue
            partition = str(row.get("partition", "")).strip().lower()
            rows.append((str(image), season, partition))
            counts[season] += 1

    if not rows:
        raise SystemExit(
            "매칭된 이미지가 0개입니다. --image-root 가 partition 폴더(test/train/...)를 "
            "직접 포함하는지, 압축이 풀렸는지 확인하세요."
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["image_path", "season", "partition"])
        writer.writerows(rows)

    print(f"manifest 저장: {out}  (rows={len(rows)}, 이미지 미발견={missing})")
    print("계절별 개수:", dict(counts))
    print("파티션:", dict(Counter(r[2] for r in rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
