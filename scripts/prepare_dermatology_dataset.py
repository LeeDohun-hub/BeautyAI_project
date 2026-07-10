"""다중 데이터셋 → 통합 피부질환 매니페스트(Tier1/Tier2 라벨).

소스: PAD-UFES-20 · DermNet · Fitzpatrick17k · SkinDisNet(기존) · 정상(얼굴정상 + 병변주변 크롭).
각 소스는 어댑터로 처리하며, 폴더가 없으면 조용히 건너뛴다(부분 다운로드도 실행 가능).

출력 CSV 컬럼: image_path, tier1, tier2, source, fitzpatrick(선택; 없으면 빈칸)

RunPod 실행 예:
    python scripts/prepare_dermatology_dataset.py \
      --root data/datasets --out data/manifests/dermatology_manifest.csv \
      --harvest-normal 4000
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from dermatology_taxonomy import (
    DERMNET,  # noqa: F401  (문서용)
    FITZ_NINE_TO_TIER2,
    FITZ_THREE_TO_TIER1,
    PAD_UFES,
    SKINDISNET,
    dermnet_lookup,
    enforce,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
Row = dict[str, str]


def _iter_images(root: Path):
    for path in root.rglob("*"):
        if path.suffix.lower() in IMAGE_EXTS:
            yield path


def _index_by_stem(root: Path) -> dict[str, Path]:
    """basename(확장자 제외) → 경로. CSV의 img_id/md5hash 매칭용."""
    index: dict[str, Path] = {}
    for path in _iter_images(root):
        index.setdefault(path.stem.lower(), path)
        index.setdefault(path.name.lower(), path)
    return index


# ── PAD-UFES-20 ───────────────────────────────────────────────────────────
def adapt_pad_ufes(root: Path) -> list[Row]:
    base = _first_existing(root, ["skin-cancer", "pad-ufes-20", "pad_ufes_20", "PAD-UFES-20"])
    if base is None:
        return []
    meta = _find_csv(base, ["metadata.csv", "PAD-UFES-20.csv"])
    if meta is None:
        return []
    index = _index_by_stem(base)
    rows: list[Row] = []
    with meta.open(encoding="utf-8", errors="ignore", newline="") as file:
        reader = csv.DictReader(file)
        fields = {f.lower(): f for f in (reader.fieldnames or [])}
        id_key = fields.get("img_id") or fields.get("image_id") or fields.get("imageid")
        dx_key = fields.get("diagnostic") or fields.get("diagnosis") or fields.get("dx")
        fitz_key = fields.get("fitspatrick") or fields.get("fitzpatrick")
        if not id_key or not dx_key:
            return []
        for record in reader:
            code = str(record.get(dx_key, "")).strip().upper()
            mapping = PAD_UFES.get(code)
            if mapping is None:
                continue
            img_id = str(record.get(id_key, "")).strip().lower()
            path = index.get(img_id) or index.get(Path(img_id).stem)
            if path is None:
                continue
            tier1, tier2 = enforce(*mapping)
            rows.append(_row(path, tier1, tier2, "pad_ufes", record.get(fitz_key, "") if fitz_key else ""))
    return rows


# ── DermNet ───────────────────────────────────────────────────────────────
def adapt_dermnet(root: Path) -> list[Row]:
    base = _first_existing(root, ["dermnet", "DermNet"])
    if base is None:
        return []
    rows: list[Row] = []
    # train/ test/ 아래 클래스 폴더. 클래스 폴더명으로 매핑.
    for image in _iter_images(base):
        # 이미지 바로 위 폴더가 클래스명.
        folder = image.parent.name
        mapping = dermnet_lookup(folder)
        if mapping is None:
            continue
        tier1, tier2 = enforce(*mapping)
        if tier1 is None:
            # 게이트 애매(혼재 폴더) → tier2만 채우고 tier1은 빈칸(게이트 학습서 제외).
            rows.append(_row(image, "", tier2, "dermnet", ""))
        else:
            rows.append(_row(image, tier1, tier2, "dermnet", ""))
    return rows


# ── Fitzpatrick17k ────────────────────────────────────────────────────────
def adapt_fitzpatrick(root: Path) -> list[Row]:
    base = _first_existing(root, ["fitzpatrick17k", "fitzpatrick-17k", "fitzpatrick_17k"])
    if base is None:
        return []
    meta = _find_csv(base, ["fitzpatrick17k.csv", "fitzpatrick.csv"])
    if meta is None:
        return []
    index = _index_by_stem(base)
    rows: list[Row] = []
    with meta.open(encoding="utf-8", errors="ignore", newline="") as file:
        reader = csv.DictReader(file)
        fields = {f.lower(): f for f in (reader.fieldnames or [])}
        id_key = fields.get("md5hash") or fields.get("hash") or fields.get("image")
        three_key = fields.get("three_partition_label")
        nine_key = fields.get("nine_partition_label")
        fitz_key = fields.get("fitzpatrick_scale") or fields.get("fitzpatrick")
        if not id_key or not three_key:
            return []
        for record in reader:
            tier1 = FITZ_THREE_TO_TIER1.get(str(record.get(three_key, "")).strip().lower())
            if tier1 is None:
                continue
            nine = str(record.get(nine_key, "")).strip().lower() if nine_key else ""
            tier2 = FITZ_NINE_TO_TIER2.get(nine, "other")
            tier1, tier2 = enforce(tier1, tier2)
            stem = str(record.get(id_key, "")).strip().lower()
            path = index.get(stem) or index.get(f"{stem}.jpg")
            if path is None:
                continue
            rows.append(_row(path, tier1, tier2, "fitzpatrick", record.get(fitz_key, "") if fitz_key else ""))
    return rows


# ── SkinDisNet(기존) ──────────────────────────────────────────────────────
def adapt_skindisnet(root: Path) -> list[Row]:
    base = root / "skindisnet" / "preprocessed"
    if not base.exists():
        return []
    rows: list[Row] = []
    for class_name, mapping in SKINDISNET.items():
        class_dir = base / class_name
        if not class_dir.exists():
            continue
        tier1, tier2 = enforce(*mapping)
        for image in _iter_images(class_dir):
            rows.append(_row(image, tier1, tier2, "skindisnet", ""))
    return rows


# ── 정상: (1) 얼굴 정상피부 폴더 ──────────────────────────────────────────
def adapt_face_normal(root: Path) -> list[Row]:
    base = root / "kaggle" / "bishalsharma000__facial-skin-datasets"
    rows: list[Row] = []
    if not base.exists():
        return rows
    for image in _iter_images(base):
        text = str(image).lower()
        if "normal" in text or "clear" in text:
            rows.append(_row(image, "normal", "", "face_normal", ""))
    return rows


# ── 정상: (3) 병변 사진의 주변부(정상 피부) 크롭 harvest ───────────────────
def harvest_normal_crops(lesion_rows: list[Row], out_dir: Path, target: int) -> list[Row]:
    """병변 이미지의 네 모서리 패치 중 '피부색'인 것만 정상으로 저장(같은 도메인 정상)."""
    if target <= 0 or not lesion_rows:
        return []
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("cv2/numpy 미설치 — 정상 크롭 harvest 생략")
        return []

    def skin_ratio_of(bgr) -> float:
        if bgr is None or bgr.size == 0:
            return 0.0
        ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
        cr, cb = ycrcb[:, :, 1], ycrcb[:, :, 2]
        mask = (cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127)
        return float(mask.mean())

    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    pool = lesion_rows[:]
    rng.shuffle(pool)
    rows: list[Row] = []
    saved = 0
    for row in pool:
        if saved >= target:
            break
        src = Path(row["image_path"])
        img = cv2.imread(str(src))
        if img is None:
            continue
        h, w = img.shape[:2]
        ph, pw = h // 4, w // 4
        # 네 모서리 패치(병변은 대개 중앙) 중 피부비율 높은 것 1개만 채택.
        corners = {
            "tl": img[0:ph, 0:pw], "tr": img[0:ph, w - pw:w],
            "bl": img[h - ph:h, 0:pw], "br": img[h - ph:h, w - pw:w],
        }
        best = max(corners.items(), key=lambda kv: skin_ratio_of(kv[1]))
        if skin_ratio_of(best[1]) < 0.6:
            continue
        dest = out_dir / f"{src.stem}_{best[0]}.jpg"
        cv2.imwrite(str(dest), best[1])
        rows.append(_row(dest, "normal", "", "lesion_periphery", ""))
        saved += 1
    print(f"정상 크롭 harvest: {saved}장 저장 → {out_dir}")
    return rows


# ── helpers ───────────────────────────────────────────────────────────────
def _row(path: Path, tier1: str, tier2: str, source: str, fitz: str) -> Row:
    return {
        "image_path": str(path),
        "tier1": tier1 or "",
        "tier2": tier2 or "",
        "source": source,
        "fitzpatrick": str(fitz or "").strip(),
    }


def _first_existing(root: Path, names: list[str]) -> Path | None:
    # kaggle 다운로드는 slug 폴더(user__dataset)로도 풀리므로 재귀 탐색까지 시도.
    for name in names:
        direct = root / name
        if direct.exists():
            return direct
    for name in names:
        for candidate in root.rglob(f"*{name}*"):
            if candidate.is_dir():
                return candidate
    return None


def _find_csv(base: Path, names: list[str]) -> Path | None:
    for name in names:
        for candidate in base.rglob(name):
            return candidate
    # 폴백: base 아래 아무 csv 중 metadata 성격
    for candidate in base.rglob("*.csv"):
        return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/datasets")
    parser.add_argument("--out", default="data/manifests/dermatology_manifest.csv")
    parser.add_argument("--harvest-normal", type=int, default=0,
                        help="병변 주변부에서 정상 크롭을 이만큼 생성(0=생략)")
    parser.add_argument("--normal-crop-dir", default="data/datasets/normal_crops")
    args = parser.parse_args()

    root = Path(args.root)
    rows: list[Row] = []
    for name, fn in [
        ("PAD-UFES-20", adapt_pad_ufes),
        ("DermNet", adapt_dermnet),
        ("Fitzpatrick17k", adapt_fitzpatrick),
        ("SkinDisNet", adapt_skindisnet),
        ("FaceNormal", adapt_face_normal),
    ]:
        got = fn(root)
        print(f"{name:16s}: {len(got):6d} rows")
        rows.extend(got)

    if args.harvest_normal > 0:
        lesion_rows = [r for r in rows if r["tier1"] in ("benign_concern", "urgent_referral")]
        rows.extend(harvest_normal_crops(lesion_rows, Path(args.normal_crop_dir), args.harvest_normal))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["image_path", "tier1", "tier2", "source", "fitzpatrick"])
        writer.writeheader()
        writer.writerows(rows)

    _summarize(rows)
    print(f"\nWrote {len(rows)} rows → {out}")
    return 0


def _summarize(rows: list[Row]) -> None:
    from collections import Counter
    t1 = Counter(r["tier1"] or "(none)" for r in rows)
    t2 = Counter(r["tier2"] or "(none)" for r in rows)
    print("\n=== Tier1 분포 ===")
    for k, v in t1.most_common():
        print(f"  {k:16s} {v:6d}")
    print("=== Tier2 분포 ===")
    for k, v in t2.most_common():
        print(f"  {k:18s} {v:6d}")


if __name__ == "__main__":
    raise SystemExit(main())
