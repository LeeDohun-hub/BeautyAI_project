"""네일 영역 검출 — 사전학습 YOLOv8 세그 모델로 파이프라인 1단계를 돌린다.

AI-Hub 04 라벨(TL_발)이 0바이트라 학습이 막혀 있어, 학습 없이 네일 마스크를 얻는
경로를 확보한 것. 모델은 손톱으로 학습됐지만 발톱에도 전이되는지를 보유 이미지로 검증한다.

모델: mnemic/nails_seg_yolov8 (CC-BY-4.0, Roboflow "Personal Projects/Nails Segmentation" 학습)
      → data/models/nails_seg_s_yolov8_v1.pt

`--crop-dir` 를 주면 검출된 네일별 크롭을 저장한다. 이게 리트리벌(B안) 인덱스의 입력이다.

Usage:
    python scripts/detect_nail_regions.py --limit 100
    python scripts/detect_nail_regions.py --source "data/.../TS_디자인데이터_발.zip" --crop-dir data/nail_crops
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import zipfile
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = PROJECT_ROOT / "data" / "models" / "nails_seg_s_yolov8_v1.pt"
DATA_04 = PROJECT_ROOT / "data" / "04.네일 및 페디큐어 데이터" / "3.개방데이터" / "1.데이터"
DEFAULT_SOURCES = [
    DATA_04 / "Validation" / "1.원천데이터" / "VS_디자인데이터_발.zip",
    DATA_04 / "Training" / "1.원천데이터" / "TS_디자인데이터_발.zip",
]
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def iter_images(source: Path, limit: int | None):
    """zip 이든 디렉터리든 (이름, BGR ndarray) 를 흘려보낸다. zip 은 추출하지 않는다."""
    count = 0
    if source.is_dir():
        names = sorted(p for p in source.rglob("*") if p.suffix.lower() in IMAGE_EXT)
        for path in names:
            if limit is not None and count >= limit:
                return
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                count += 1
                yield path.name, img
        return

    with zipfile.ZipFile(source) as zf:
        names = sorted(n for n in zf.namelist() if n.lower().endswith(IMAGE_EXT))
        for name in names:
            if limit is not None and count >= limit:
                return
            img = cv2.imdecode(np.frombuffer(zf.read(name), np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                count += 1
                yield name, img


def run(source: Path, model, conf: float, limit: int | None,
        overlay_dir: Path | None, crop_dir: Path | None) -> dict:
    per_image: list[dict] = []

    for name, img in iter_images(source, limit):
        res = model.predict(img, conf=conf, verbose=False)[0]
        boxes = res.boxes
        n_det = 0 if boxes is None else len(boxes)
        confs = [] if n_det == 0 else [float(c) for c in boxes.conf]

        mask_ratio = 0.0
        if res.masks is not None and len(res.masks) > 0:
            merged = res.masks.data.cpu().numpy().max(axis=0)
            mask_ratio = float(merged.sum()) / float(merged.size)

        per_image.append({
            "file": name,
            "width": int(img.shape[1]),
            "height": int(img.shape[0]),
            "detections": n_det,
            "conf_max": max(confs) if confs else 0.0,
            "conf_min": min(confs) if confs else 0.0,
            "mask_area_ratio": mask_ratio,
        })

        stem = Path(name).stem
        if overlay_dir is not None:
            overlay_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(overlay_dir / f"{stem}.png"), res.plot())

        if crop_dir is not None and n_det:
            crop_dir.mkdir(parents=True, exist_ok=True)
            for i, box in enumerate(boxes.xyxy.cpu().numpy().astype(int)):
                x1, y1, x2, y2 = box
                crop = img[max(y1, 0):y2, max(x1, 0):x2]
                if crop.size:
                    cv2.imwrite(str(crop_dir / f"{stem}_nail{i:02d}.png"), crop)

    return summarize(source, per_image, conf)


def summarize(source: Path, per_image: list[dict], conf: float) -> dict:
    total = len(per_image)
    if not total:
        return {"source": source.name, "images": 0}

    dets = [r["detections"] for r in per_image]
    hit = [r for r in per_image if r["detections"] > 0]
    confs = [r["conf_max"] for r in hit]
    ratios = [r["mask_area_ratio"] for r in hit]

    return {
        "source": source.name,
        "conf_threshold": conf,
        "images": total,
        "images_with_detection": len(hit),
        "detection_rate": len(hit) / total,
        "detections_total": sum(dets),
        "detections_per_image_mean": sum(dets) / total,
        "detections_histogram": dict(sorted(Counter(dets).items())),
        "conf_max_mean": statistics.mean(confs) if confs else 0.0,
        "conf_max_median": statistics.median(confs) if confs else 0.0,
        "mask_area_ratio_mean": statistics.mean(ratios) if ratios else 0.0,
        "zero_detection_files": [r["file"] for r in per_image if r["detections"] == 0][:20],
        "low_detection_files": [
            r["file"] for r in per_image if 0 < r["detections"] <= 2
        ][:20],
    }


def print_summary(s: dict) -> None:
    if not s.get("images"):
        print(f"  (이미지 없음: {s['source']})")
        return
    print(f"\n== {s['source']}  (conf>={s['conf_threshold']})")
    print(f"  이미지            : {s['images']}")
    print(f"  검출된 이미지     : {s['images_with_detection']} ({s['detection_rate']*100:.1f}%)")
    print(f"  총 검출 수        : {s['detections_total']}")
    print(f"  이미지당 평균     : {s['detections_per_image_mean']:.2f}")
    print(f"  검출수 분포       : {s['detections_histogram']}")
    print(f"  conf(최대) 평균   : {s['conf_max_mean']:.3f} / 중앙값 {s['conf_max_median']:.3f}")
    print(f"  마스크 면적 비율  : {s['mask_area_ratio_mean']*100:.2f}%")
    if s["zero_detection_files"]:
        print(f"  미검출 예시       : {s['zero_detection_files'][:5]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, action="append", help="zip 또는 이미지 디렉터리 (반복 지정 가능)")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=None, help="소스당 최대 이미지 수")
    ap.add_argument("--overlay-dir", type=Path, default=None, help="오버레이 시각화 저장 경로")
    ap.add_argument("--crop-dir", type=Path, default=None, help="네일별 크롭 저장 경로(리트리벌 인덱스 입력)")
    ap.add_argument("--json-out", type=Path, default=None, help="요약 통계 JSON 저장 경로")
    args = ap.parse_args()

    if not args.model.exists():
        print(f"모델 없음: {args.model}", file=sys.stderr)
        print("  huggingface_hub 로 mnemic/nails_seg_yolov8 의 nails_seg_s_yolov8_v1.pt 를 받아 두세요.", file=sys.stderr)
        return 1

    from ultralytics import YOLO  # 무거우므로 인자 검증 후 로드

    model = YOLO(str(args.model))
    print(f"모델: {args.model.name} | task={model.task} | classes={model.names}")

    sources = args.source or [p for p in DEFAULT_SOURCES if p.exists() and p.stat().st_size > 0]
    results = []
    for src in sources:
        if not src.exists() or (src.is_file() and src.stat().st_size == 0):
            print(f"건너뜀(없음/0바이트): {src}")
            continue
        summary = run(src, model, args.conf, args.limit, args.overlay_dir, args.crop_dir)
        print_summary(summary)
        results.append(summary)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 저장: {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
