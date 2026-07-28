"""네일 디자인 리트리벌 인덱스 구축 (설계문서 B안 MVP) — 학습 없음.

파이프라인: 이미지 → 네일 검출/라벨 → 크롭 → EfficientNet-B0 임베딩 + 대표색 → 인덱스.

백본은 프로젝트가 이미 쓰는 EfficientNet-B0(ImageNet 사전학습, 캐시에 있음)를 그대로 쓴다.
새 백본을 받지 않고 스택도 일치시키기 위함. 임베딩은 L2 정규화해 코사인 유사도로 검색한다.

크롭 출처는 두 갈래다:
  - AI-Hub 04 발 이미지(zip) → 라벨이 없으므로 YOLOv8 세그 모델로 검출
  - Roboflow 손 데이터 → **정답 폴리곤 라벨이 있으므로 그걸로 크롭**(검출보다 빠르고 정확)

Usage:
    python scripts/build_nail_design_index.py                     # 발 전체 + 손 valid
    python scripts/build_nail_design_index.py --limit-foot 100 --limit-hand 50
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np

# reconfigure 를 쓴다(TextIOWrapper 로 감싸면 이 모듈을 import 하는 쪽에서 이중 래핑돼
# 먼저 만들어진 래퍼가 GC 될 때 버퍼가 닫히고 "I/O operation on closed file" 이 난다).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / "data" / "models" / "nails_seg_s_yolov8_v1.pt"
DATA_04 = PROJECT_ROOT / "data" / "04.네일 및 페디큐어 데이터" / "3.개방데이터" / "1.데이터"
FOOT_ZIPS = [
    DATA_04 / "Training" / "1.원천데이터" / "TS_디자인데이터_발.zip",
    DATA_04 / "Validation" / "1.원천데이터" / "VS_디자인데이터_발.zip",
]
HAND_ROOT = PROJECT_ROOT / "data" / "nail_reference" / "nails_segmentation_v51_yolov8"
INDEX_DIR = PROJECT_ROOT / "data" / "nail_index"

MIN_CROP_PX = 32   # 이보다 작은 크롭은 버린다(초점 흐림·새끼발톱 — 리포트 §4)
EMBED_SIZE = 128


# --------------------------------------------------------------------------- 임베딩

class Embedder:
    """EfficientNet-B0 penultimate feature(1280d). 배치 추론."""

    def __init__(self) -> None:
        import torch
        from torchvision import models, transforms

        self.torch = torch
        weights = models.EfficientNet_B0_Weights.IMAGENET1K_V1
        net = models.efficientnet_b0(weights=weights)
        net.classifier = torch.nn.Identity()
        net.eval()
        self.net = net
        self.tf = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

    def __call__(self, crops: list[np.ndarray]) -> np.ndarray:
        torch = self.torch
        batch = []
        for c in crops:
            rgb = cv2.cvtColor(cv2.resize(c, (EMBED_SIZE, EMBED_SIZE)), cv2.COLOR_BGR2RGB)
            batch.append(self.tf(rgb))
        with torch.no_grad():
            feat = self.net(torch.stack(batch)).cpu().numpy().astype(np.float32)
        norm = np.linalg.norm(feat, axis=1, keepdims=True)
        return feat / np.clip(norm, 1e-8, None)


def dominant_color(crop: np.ndarray) -> tuple[list[float], str]:
    """크롭 중앙부의 대표색을 Lab 과 hex 로 반환. 반사 하이라이트는 제외한다."""
    h, w = crop.shape[:2]
    y0, y1 = int(h * 0.2), max(int(h * 0.8), int(h * 0.2) + 1)
    x0, x1 = int(w * 0.2), max(int(w * 0.8), int(w * 0.2) + 1)
    center = crop[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    if len(center) < 8:
        center = crop.reshape(-1, 3).astype(np.float32)

    lab = cv2.cvtColor(center.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2LAB)
    lab = lab.reshape(-1, 3).astype(np.float32)
    # 젤네일은 정반사 하이라이트가 크다 — L 상위 15%를 빼야 흰색으로 쏠리지 않는다.
    keep = lab[:, 0] <= np.percentile(lab[:, 0], 85)
    if keep.sum() >= 8:
        lab, center = lab[keep], center[keep]

    from sklearn.cluster import KMeans

    k = min(3, max(1, len(lab) // 50))
    if k > 1:
        km = KMeans(n_clusters=k, n_init=3, random_state=0).fit(lab)
        biggest = np.argmax(np.bincount(km.labels_))
        lab_mean = km.cluster_centers_[biggest]
        bgr_mean = center[km.labels_ == biggest].mean(axis=0)
    else:
        lab_mean = lab.mean(axis=0)
        bgr_mean = center.mean(axis=0)

    b, g, r = (int(np.clip(v, 0, 255)) for v in bgr_mean)
    # OpenCV Lab(uint8) → 실제 Lab 스케일
    L, A, B = float(lab_mean[0]) * 100 / 255, float(lab_mean[1]) - 128, float(lab_mean[2]) - 128
    return [round(L, 2), round(A, 2), round(B, 2)], f"#{r:02x}{g:02x}{b:02x}"


# --------------------------------------------------------------------------- 크롭 소스

def _boxes_from_yolo_label(label_path: Path, w: int, h: int) -> list[tuple[int, int, int, int]]:
    """Roboflow YOLO 세그 라벨(정규화 폴리곤)에서 바운딩박스를 만든다."""
    boxes = []
    for line in label_path.read_text().splitlines():
        parts = line.split()
        if len(parts) < 7:
            continue
        pts = np.array([float(v) for v in parts[1:]], dtype=np.float32).reshape(-1, 2)
        xs, ys = pts[:, 0] * w, pts[:, 1] * h
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    return boxes


def iter_foot_crops(model, limit: int | None):
    for zpath in FOOT_ZIPS:
        if not zpath.exists() or zpath.stat().st_size == 0:
            continue
        split = "train" if zpath.name.startswith("TS") else "valid"
        with zipfile.ZipFile(zpath) as zf:
            names = sorted(n for n in zf.namelist() if n.lower().endswith(".png"))
            if limit is not None:
                names = names[:limit]
            for name in names:
                img = cv2.imdecode(np.frombuffer(zf.read(name), np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    continue
                res = model.predict(img, conf=0.4, verbose=False)[0]
                if res.boxes is None:
                    continue
                for i, box in enumerate(res.boxes.xyxy.cpu().numpy().astype(int)):
                    yield "foot", split, Path(name).stem, i, img, tuple(box)


def iter_hand_crops(limit: int | None):
    """정답 라벨 기반 크롭(검출 불필요)."""
    for split in ("valid", "train", "test"):
        img_dir, lbl_dir = HAND_ROOT / split / "images", HAND_ROOT / split / "labels"
        if not img_dir.is_dir():
            continue
        files = sorted(img_dir.glob("*.jpg")) + sorted(img_dir.glob("*.png"))
        if limit is not None:
            files = files[:limit]
        for path in files:
            img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            lbl = lbl_dir / (path.stem + ".txt")
            if not lbl.exists():
                continue
            h, w = img.shape[:2]
            for i, box in enumerate(_boxes_from_yolo_label(lbl, w, h)):
                yield "hand", split, path.stem, i, img, box


# --------------------------------------------------------------------------- 빌드

def build(limit_foot: int | None, limit_hand: int | None, batch: int) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    thumbs = INDEX_DIR / "thumbs"
    thumbs.mkdir(exist_ok=True)

    embedder = Embedder()
    model = None
    if limit_foot != 0:
        from ultralytics import YOLO
        model = YOLO(str(MODEL_PATH))

    meta: list[dict] = []
    vectors: list[np.ndarray] = []
    pending: list[np.ndarray] = []
    skipped_small = 0

    sources = []
    if model is not None:
        sources.append(iter_foot_crops(model, limit_foot))
    if limit_hand != 0:
        sources.append(iter_hand_crops(limit_hand))

    def flush():
        if pending:
            vectors.append(embedder(pending))
            pending.clear()

    for src in sources:
        for region, split, stem, idx, img, (x1, y1, x2, y2) in src:
            x1, y1 = max(x1, 0), max(y1, 0)
            crop = img[y1:y2, x1:x2]
            if crop.size == 0 or max(crop.shape[:2]) < MIN_CROP_PX:
                skipped_small += 1
                continue
            lab, hex_color = dominant_color(crop)
            cid = f"{region}_{stem}_{idx:02d}"
            cv2.imwrite(str(thumbs / f"{cid}.png"), cv2.resize(crop, (64, 64)))
            meta.append({
                "id": cid, "region": region, "split": split, "design_id": stem,
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                "color_lab": lab, "color_hex": hex_color,
            })
            pending.append(crop)
            if len(pending) >= batch:
                flush()
                print(f"  ... {len(meta)}개 임베딩", flush=True)
    flush()

    if not meta:
        print("크롭이 하나도 없습니다.", file=sys.stderr)
        return

    emb = np.vstack(vectors)
    np.save(INDEX_DIR / "embeddings.npy", emb)
    (INDEX_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    regions = {}
    for m in meta:
        regions[m["region"]] = regions.get(m["region"], 0) + 1
    print(f"\n인덱스 완료: {emb.shape[0]}개 × {emb.shape[1]}차원")
    print(f"  부위별: {regions}")
    print(f"  최소크기({MIN_CROP_PX}px) 미달로 제외: {skipped_small}개")
    print(f"  저장: {INDEX_DIR.relative_to(PROJECT_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit-foot", type=int, default=None, help="zip 당 이미지 수 제한(0=발 제외)")
    ap.add_argument("--limit-hand", type=int, default=250, help="split 당 이미지 수 제한(0=손 제외)")
    ap.add_argument("--batch", type=int, default=64)
    args = ap.parse_args()

    if not MODEL_PATH.exists() and args.limit_foot != 0:
        print(f"모델 없음: {MODEL_PATH} — fetch_nail_reference_data.py 를 먼저 실행하세요.", file=sys.stderr)
        return 1
    build(args.limit_foot, args.limit_hand, args.batch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
