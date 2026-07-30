"""네일 리트리벌 **범주 정확도** 평가 — AI-Hub 04 메타데이터 라벨 기준.

기존 `eval_nail_retrieval.py` 는 색(ΔE)만 봤다. 범주 라벨이 없었기 때문이다.
AI-Hub 04 메타데이터 zip 을 확보해 `pattern_id/color_id/shape_id` 를 붙일 수 있게 됐으므로,
"검색된 디자인이 실제로 같은 범주인가" 를 잰다.

규약은 기존 eval 과 동일하다 — **leave-one-design-out**(같은 사진 크롭 전부 제외),
하이브리드 점수 `score = cos유사도 - λ·(ΔE/100)`.

⚠️ 조인 가능한 건 **발(foot)뿐**이다. 손 크롭은 Roboflow 출신이라 AI-Hub 디자인ID가 없다.

⚠️ pattern/color 는 **다중 라벨**이고 분포가 심하게 치우쳐 있다(원컬러·파츠가 전체의 상당수).
그래서 "하나라도 겹치면 정답"(any-share)은 무작위로도 쉽게 높게 나온다.
**반드시 랜덤 베이스라인과 함께 읽어야 하고**, 엄밀한 수치는 Jaccard 쪽이다.

라벨 단위 주의: `design_meta_info` 는 항상 길이 1이라 pattern/color/shape 는
**이미지(디자인) 단위** 라벨이다. 같은 사진에서 나온 크롭들은 같은 라벨을 공유한다.

Usage:
    python scripts/eval_nail_category.py
    python scripts/eval_nail_category.py --samples 800 --topk 5 --color-weight 0.5
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT_ROOT / "data" / "nail_index"
META_DIR = (PROJECT_ROOT / "data" / "04.네일 및 페디큐어 데이터"
            / "3.개방데이터" / "1.데이터" / "Other")
META_ZIPS = {
    "foot": META_DIR / "메타데이터_디자인데이터_발.zip",
    "hand": META_DIR / "메타데이터_디자인데이터_손.zip",
}
ATTRS = ("pattern_id", "color_id", "shape_id")


def load_labels() -> dict[str, dict[str, set[str]]]:
    """메타데이터 zip 에서 디자인ID → {속성: 라벨집합} 을 뽑는다(압축 해제 없이)."""
    labels: dict[str, dict[str, set[str]]] = {}
    for zpath in META_ZIPS.values():
        if not zpath.exists():
            continue
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                if not name.endswith("_metadata.json"):
                    continue
                design = Path(name).name.replace("_metadata.json", "")
                info = json.loads(z.read(name).decode("utf-8-sig"))["design_meta_info"]
                if not info:
                    continue
                # design_meta_info 는 전 파일 길이 1 — 이미지 단위 라벨이다.
                entry = info[0]
                labels[design] = {a: set(entry.get(a) or []) for a in ATTRS}
    return labels


def index_key(design_id: str) -> str:
    """인덱스의 design_id('D19001_02_RGB_01') → 메타데이터 키('D19001_02')."""
    return design_id.replace("_RGB_01", "")


def _share(a: set[str], b: set[str]) -> bool:
    return bool(a & b)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", choices=["foot", "hand", "all"], default="foot",
                    help="기본 foot — 손은 Roboflow 출신이라 라벨 조인이 안 된다")
    ap.add_argument("--samples", type=int, default=400)
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--color-weight", type=float, default=0.5,
                    help="하이브리드 점수 λ (MVP 채택값 0.5)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if not any(p.exists() for p in META_ZIPS.values()):
        print(f"메타데이터 zip 이 없습니다: {META_DIR}", file=sys.stderr)
        return 1

    emb = np.load(INDEX_DIR / "embeddings.npy")
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    labs = np.array([m["color_lab"] for m in meta], dtype=np.float32)
    designs = np.array([m["design_id"] for m in meta])
    regions = np.array([m["region"] for m in meta])

    labels = load_labels()
    keys = np.array([index_key(d) for d in designs])
    labeled = np.array([k in labels for k in keys])

    pool = np.arange(len(meta)) if args.region == "all" else np.where(regions == args.region)[0]
    pool = pool[labeled[pool]]          # 라벨 붙은 크롭만 질의로 쓴다
    if len(pool) == 0:
        print(f"라벨이 조인된 항목이 없습니다: region={args.region}", file=sys.stderr)
        return 1

    # 후보 풀도 라벨 있는 것만 — 라벨 없는 항목이 top-K 에 오면 채점 불능이라
    cand = np.where(labeled)[0]
    cand_mask = np.zeros(len(meta), dtype=bool)
    cand_mask[cand] = True

    print(f"\n=== 범주 정확도 평가 (region={args.region}, λ={args.color_weight}, top-{args.topk}) ===")
    print(f"인덱스 {len(meta)}개 중 라벨 조인 {int(labeled.sum())}개 "
          f"({labeled.sum()/len(meta)*100:.1f}%) · 질의 풀 {len(pool)}개")

    rng = np.random.default_rng(args.seed)
    qs = rng.choice(pool, size=min(args.samples, len(pool)), replace=False)

    hit = {a: [] for a in ATTRS}          # top-K 안에 라벨 공유 항목 존재
    p_at1 = {a: [] for a in ATTRS}        # top-1 이 라벨 공유
    jac1 = {a: [] for a in ATTRS}         # top-1 과의 Jaccard
    r_p1 = {a: [] for a in ATTRS}         # 랜덤 베이스라인
    r_j1 = {a: [] for a in ATTRS}

    for qi in qs:
        sims = emb @ emb[qi]
        if args.color_weight:
            sims = sims - args.color_weight * (np.linalg.norm(labs - labs[qi], axis=1) / 100.0)
        sims[designs == designs[qi]] = -np.inf   # 같은 사진 제외
        sims[~cand_mask] = -np.inf               # 라벨 없는 후보 제외
        top = np.argpartition(sims, -args.topk)[-args.topk:]
        top = top[np.argsort(sims[top])[::-1]]

        ql = labels[keys[qi]]
        valid = np.where((designs != designs[qi]) & cand_mask)[0]
        rl = labels[keys[rng.choice(valid)]]

        for a in ATTRS:
            tops = [labels[keys[t]][a] for t in top]
            hit[a].append(any(_share(ql[a], t) for t in tops))
            p_at1[a].append(_share(ql[a], tops[0]))
            jac1[a].append(_jaccard(ql[a], tops[0]))
            r_p1[a].append(_share(ql[a], rl[a]))
            r_j1[a].append(_jaccard(ql[a], rl[a]))

    n = len(qs)
    name = {"pattern_id": "패턴", "color_id": "색상", "shape_id": "모양"}
    print(f"\n질의 {n}개 · 리트리벌 vs 랜덤 (랜덤보다 확실히 높아야 의미 있음)\n")
    print(f"{'속성':<6} {'공유@1':>8} {'랜덤@1':>8} {'개선':>8}   "
          f"{'Jaccard@1':>10} {'랜덤J':>8} {'개선':>8}   {'공유@'+str(args.topk):>8}")
    print("-" * 78)
    for a in ATTRS:
        p, rp = np.mean(p_at1[a]) * 100, np.mean(r_p1[a]) * 100
        j, rj = np.mean(jac1[a]), np.mean(r_j1[a])
        print(f"{name[a]:<6} {p:7.1f}% {rp:7.1f}% {p-rp:+7.1f}p   "
              f"{j:10.3f} {rj:8.3f} {j-rj:+8.3f}   {np.mean(hit[a])*100:7.1f}%")
    print("\n※ 패턴·색상은 다중라벨이라 '공유'는 하나만 겹쳐도 참 — 랜덤 대비 개선폭으로 읽을 것.")
    print("※ 모양(shape)은 단일값이라 공유@1 이 곧 정확도다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
