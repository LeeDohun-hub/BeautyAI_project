"""네일 리트리벌 인덱스 정량 평가 — leave-one-design-out.

인덱스에 저장된 임베딩만 쓰므로 이미지 재처리·재빌드가 필요 없다.
질의 크롭과 **같은 디자인ID(같은 사진)에서 나온 크롭을 전부 제외**하고 최근접을 찾는다.
같은 사진의 다른 손발톱을 맞히는 건 자명하므로 그걸 빼야 '다른 디자인을 제대로 찾는지'가 보인다.

지표
  - ΔE(top-1): 질의와 top-1 의 대표색 색차(CIE76). 낮을수록 색이 맞는다.
  - 랜덤 베이스라인: 같은 조건에서 무작위 항목과의 ΔE. 리트리벌이 이보다 확실히 낮아야 의미가 있다.
  - color hit@K: top-K 안에 ΔE<=임계값인 항목이 하나라도 있는 비율.

Usage:
    python scripts/eval_nail_retrieval.py
    python scripts/eval_nail_retrieval.py --region foot --samples 500 --topk 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT_ROOT / "data" / "nail_index"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", choices=["foot", "hand", "all"], default="all")
    ap.add_argument("--samples", type=int, default=400)
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--de-threshold", type=float, default=15.0, help="색이 '비슷하다'고 볼 ΔE 상한")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--color-weight", type=float, default=0.0,
                    help="하이브리드 점수 가중치 λ: score = cos유사도 - λ·(ΔE/100). "
                         "ImageNet 임베딩은 질감·형태에 치우쳐 색이 덜 맞는다 — 색거리를 섞어 보정한다.")
    args = ap.parse_args()

    emb = np.load(INDEX_DIR / "embeddings.npy")
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    labs = np.array([m["color_lab"] for m in meta], dtype=np.float32)
    designs = np.array([m["design_id"] for m in meta])
    regions = np.array([m["region"] for m in meta])

    pool = np.arange(len(meta)) if args.region == "all" else np.where(regions == args.region)[0]
    if len(pool) == 0:
        print(f"해당 부위 항목이 없습니다: {args.region}", file=sys.stderr)
        return 1

    rng = np.random.default_rng(args.seed)
    qs = rng.choice(pool, size=min(args.samples, len(pool)), replace=False)

    de_top1, de_rand, hits, sims_top1, cross_region = [], [], [], [], 0
    for qi in qs:
        sims = emb @ emb[qi]
        if args.color_weight:
            sims = sims - args.color_weight * (np.linalg.norm(labs - labs[qi], axis=1) / 100.0)
        # 같은 사진(디자인ID)에서 나온 크롭 전부 제외 — 자명한 매칭 방지
        sims[designs == designs[qi]] = -np.inf
        top = np.argpartition(sims, -args.topk)[-args.topk:]
        top = top[np.argsort(sims[top])[::-1]]

        d = np.linalg.norm(labs[top] - labs[qi], axis=1)
        de_top1.append(float(d[0]))
        sims_top1.append(float(sims[top[0]]))
        hits.append(bool((d <= args.de_threshold).any()))
        if regions[top[0]] != regions[qi]:
            cross_region += 1

        valid = np.where(designs != designs[qi])[0]
        de_rand.append(float(np.linalg.norm(labs[rng.choice(valid)] - labs[qi])))

    n = len(qs)
    de_top1, de_rand = np.array(de_top1), np.array(de_rand)
    print(f"\n=== leave-one-design-out 평가 (region={args.region}, 질의 {n}개, top-{args.topk}) ===")
    print(f"인덱스 규모        : {len(meta)}개 (foot {int((regions=='foot').sum())} / hand {int((regions=='hand').sum())})")
    print(f"top-1 유사도       : 평균 {np.mean(sims_top1):.3f}")
    print(f"ΔE(top-1)          : 평균 {de_top1.mean():5.1f}  중앙값 {np.median(de_top1):5.1f}")
    print(f"ΔE(랜덤 베이스라인): 평균 {de_rand.mean():5.1f}  중앙값 {np.median(de_rand):5.1f}")
    improve = (1 - de_top1.mean() / de_rand.mean()) * 100
    print(f"  → 색차 개선       : {improve:.1f}% (낮을수록 좋음, 0%면 무작위와 동일)")
    print(f"color hit@{args.topk} (ΔE<={args.de_threshold:.0f}) : {sum(hits)/n*100:.1f}%")
    print(f"부위가 바뀐 top-1  : {cross_region/n*100:.1f}% (발↔손 교차)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
