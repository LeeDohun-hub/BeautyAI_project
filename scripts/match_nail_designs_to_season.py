"""퍼스널컬러 시즌 ↔ 네일 디자인 인덱스 매칭 (팔레트 브리지).

인덱스 크롭의 대표색(Lab)을 `app.services.nail_palette` 로 시즌 팔레트와 맞춰,
"이 시즌에 어울리는 디자인 top-K" 를 뽑는다. 동시에 **시즌별 커버리지**를 낸다 —
특정 시즌에 맞는 디자인이 인덱스에 없으면 그 시즌 사용자에게는 기능이 빈 화면이 된다.

Usage:
    python scripts/match_nail_designs_to_season.py                       # 전 시즌 커버리지
    python scripts/match_nail_designs_to_season.py --tone cool --subtype deep --topk 10 \
        --contact-sheet out.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT_ROOT / "data" / "nail_index"
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.nail_palette import nail_color_fit  # noqa: E402
from app.services.personal_color_analyzer import PROFILES  # noqa: E402

# 이 점수 미만이면 "어울린다"고 보지 않는다(ΔE 25 ≈ 눈에 띄게 다른 색).
FIT_THRESHOLD = 50.0


def chroma(lab) -> float:
    """C* = sqrt(a²+b²). 낮으면 민낯·클리어에 가까워 '디자인 색'으로 보기 어렵다."""
    return (lab[1] ** 2 + lab[2] ** 2) ** 0.5


def load_meta(min_chroma: float = 0.0) -> list[dict]:
    path = INDEX_DIR / "meta.json"
    if not path.exists():
        raise SystemExit("인덱스가 없습니다 — build_nail_design_index.py 를 먼저 실행하세요.")
    meta = json.loads(path.read_text(encoding="utf-8"))
    if min_chroma <= 0:
        return meta
    kept = [m for m in meta if chroma(m["color_lab"]) >= min_chroma]
    print(f"채도 필터 C*>={min_chroma:.0f}: {len(meta)} → {len(kept)}개 "
          f"({(1 - len(kept)/len(meta))*100:.1f}% 제외 — 민낯·클리어 추정)")
    return kept


def score_all(meta: list[dict], tone: str, subtype: str) -> list[tuple[dict, object]]:
    rows = [(m, nail_color_fit(tuple(m["color_lab"]), tone, subtype)) for m in meta]
    rows.sort(key=lambda r: r[1].delta_e)
    return rows


def coverage(meta: list[dict]) -> None:
    print(f"\n=== 시즌별 커버리지 (인덱스 {len(meta)}개, 적합 기준 {FIT_THRESHOLD:.0f}점 이상) ===")
    print(f"{'시즌':<16} {'적합':>7} {'비율':>7}  {'상위색조 분포'}")
    for (tone, subtype), profile in PROFILES.items():
        rows = score_all(meta, tone, subtype)
        good = [r for r in rows if r[1].score >= FIT_THRESHOLD]
        by_shade: dict[str, int] = {}
        for _m, fit in good:
            by_shade[fit.name] = by_shade.get(fit.name, 0) + 1
        top = ", ".join(f"{k} {v}" for k, v in sorted(by_shade.items(), key=lambda kv: -kv[1])[:3])
        print(f"{profile.label:<16} {len(good):>7} {len(good)/len(meta)*100:>6.1f}%  {top or '-'}")


def show_top(meta: list[dict], tone: str, subtype: str, topk: int, sheet: Path | None) -> None:
    profile = PROFILES.get((tone, subtype)) or PROFILES[(tone, "soft")]
    rows = score_all(meta, tone, subtype)[:topk]
    print(f"\n=== {profile.label} 추천 디자인 top-{topk} ===")
    for i, (m, fit) in enumerate(rows, 1):
        print(f"  {i:>2}. score={fit.score:>5.1f}  ΔE={fit.delta_e:>5.2f}  {fit.name:<10} "
              f"{m['color_hex']}  {m['region']:<4} {m['design_id']}")

    if sheet:
        import cv2
        import numpy as np

        cell = 96
        cols = min(len(rows), 10)
        rowsn = (len(rows) + cols - 1) // cols
        canvas = np.full((rowsn * cell, cols * cell, 3), 30, np.uint8)
        for i, (m, _fit) in enumerate(rows):
            thumb = cv2.imread(str(INDEX_DIR / "thumbs" / f"{m['id']}.png"))
            if thumb is None:
                continue
            r, c = divmod(i, cols)
            canvas[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = cv2.resize(thumb, (cell, cell))
        sheet.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(sheet), canvas)
        print(f"\n컨택트시트: {sheet}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tone", choices=["warm", "cool"], default=None)
    ap.add_argument("--subtype", choices=["light", "deep", "soft", "bright"], default=None)
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--contact-sheet", type=Path, default=None)
    ap.add_argument("--min-chroma", type=float, default=0.0,
                    help="C* 하한. 민낯·클리어 크롭을 빼고 실제 '색이 있는' 디자인만 보려면 15 정도.")
    args = ap.parse_args()

    meta = load_meta(args.min_chroma)
    if args.tone and args.subtype:
        show_top(meta, args.tone, args.subtype, args.topk, args.contact_sheet)
    else:
        coverage(meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
