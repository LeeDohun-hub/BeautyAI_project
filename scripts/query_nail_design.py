"""네일 디자인 리트리벌 질의 (설계문서 B안 MVP).

사진 → 네일 검출 → 크롭 → 임베딩 → 인덱스에서 코사인 최근접 → 유사 디자인 top-K.
대표색(Lab)도 함께 내보내, 퍼스널컬러 nail 컬럼의 색상 추천으로 이어붙일 수 있게 한다.

인덱스는 `scripts/build_nail_design_index.py` 로 먼저 만들어야 한다.

Usage:
    python scripts/query_nail_design.py --image my_hand.jpg --topk 5
    python scripts/query_nail_design.py --image q.png --contact-sheet out.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT_ROOT / "data" / "nail_index"
MODEL_PATH = PROJECT_ROOT / "data" / "models" / "nails_seg_s_yolov8_v1.pt"

sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from app.services.nail_design_index import Embedder, dominant_color  # noqa: E402


def load_index() -> tuple[np.ndarray, list[dict]]:
    emb = np.load(INDEX_DIR / "embeddings.npy")
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    if len(emb) != len(meta):
        raise SystemExit(f"인덱스 불일치: embeddings {len(emb)} vs meta {len(meta)}")
    return emb, meta


def delta_e(lab1: list[float], lab2: list[float]) -> float:
    """CIE76 색차 — 리트리벌 결과가 '색까지' 맞는지 보는 보조 지표."""
    return float(np.linalg.norm(np.array(lab1) - np.array(lab2)))


def query(image_path: Path, topk: int, conf: float, sheet_out: Path | None,
          color_weight: float, exclude_design: str | None) -> None:
    from ultralytics import YOLO

    emb_index, meta = load_index()
    index_labs = np.array([m["color_lab"] for m in meta], dtype=np.float32)
    index_designs = np.array([m["design_id"] for m in meta])
    embedder = Embedder()
    model = YOLO(str(MODEL_PATH))

    img = cv2.imdecode(np.fromfile(image_path, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"이미지를 읽을 수 없습니다: {image_path}")

    res = model.predict(img, conf=conf, verbose=False)[0]
    if res.boxes is None or len(res.boxes) == 0:
        print("네일이 검출되지 않았습니다.")
        return

    boxes = res.boxes.xyxy.cpu().numpy().astype(int)
    confs = [float(c) for c in res.boxes.conf]
    # 가장 크게 찍힌 네일을 대표로 질의(엄지·검지가 보통 가장 선명)
    areas = [(x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in boxes]
    order = np.argsort(areas)[::-1]

    rows = []
    for rank, bi in enumerate(order[:3]):
        x1, y1, x2, y2 = boxes[bi]
        crop = img[max(y1, 0):y2, max(x1, 0):x2]
        if crop.size == 0:
            continue
        q_lab, q_hex = dominant_color(crop)
        q_vec = embedder([crop])[0]
        # 하이브리드 점수: ImageNet 임베딩은 질감·형태에 치우쳐 색이 덜 맞는다(실측 ΔE 23.4).
        # 색거리를 섞으면 λ=0.5 에서 ΔE 11.4 / color hit@5 96% 로 오르고 임베딩 유사도는
        # 0.712→0.635 로만 떨어진다(eval_nail_retrieval.py 스윕).
        sims = emb_index @ q_vec
        if color_weight:
            sims = sims - color_weight * (np.linalg.norm(index_labs - np.array(q_lab), axis=1) / 100.0)
        if exclude_design:
            sims = np.where(index_designs == exclude_design, -np.inf, sims)
        top = np.argsort(sims)[::-1][:topk]

        print(f"\n=== 질의 네일 #{rank + 1} (conf {confs[bi]:.2f}, {x2 - x1}x{y2 - y1}px, 대표색 {q_hex}) ===")
        for j, i in enumerate(top):
            m = meta[i]
            print(f"  {j + 1}. sim={sims[i]:.3f}  ΔE={delta_e(q_lab, m['color_lab']):5.1f}  "
                  f"{m['region']:4} {m['design_id']}  {m['color_hex']}")
        rows.append((crop, [(meta[i], float(sims[i])) for i in top]))

    if sheet_out and rows:
        make_sheet(rows, sheet_out)
        print(f"\n컨택트시트: {sheet_out}")


def make_sheet(rows, out: Path) -> None:
    """왼쪽=질의 크롭, 오른쪽=top-K 썸네일."""
    cell = 96
    cols = 1 + max(len(r[1]) for r in rows)
    sheet = np.full((len(rows) * cell, cols * cell, 3), 30, np.uint8)
    for r, (crop, matches) in enumerate(rows):
        y = r * cell
        sheet[y:y + cell, 0:cell] = cv2.resize(crop, (cell, cell))
        for c, (m, _sim) in enumerate(matches, start=1):
            thumb = cv2.imread(str(INDEX_DIR / "thumbs" / f"{m['id']}.png"))
            if thumb is not None:
                sheet[y:y + cell, c * cell:(c + 1) * cell] = cv2.resize(thumb, (cell, cell))
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--contact-sheet", type=Path, default=None)
    ap.add_argument("--color-weight", type=float, default=0.5,
                    help="색거리 가중치 λ (0=임베딩만). 기본 0.5 는 eval 스윕에서 고른 균형점.")
    ap.add_argument("--exclude-design", default=None,
                    help="이 디자인ID 의 크롭을 결과에서 제외(인덱스에 든 사진으로 시연할 때).")
    args = ap.parse_args()

    if not (INDEX_DIR / "embeddings.npy").exists():
        print("인덱스가 없습니다 — build_nail_design_index.py 를 먼저 실행하세요.", file=sys.stderr)
        return 1
    query(args.image, args.topk, args.conf, args.contact_sheet,
          args.color_weight, args.exclude_design)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
