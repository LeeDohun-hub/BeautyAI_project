"""네일 리트리벌 정확도 측정 — 사람이 판정할 리뷰 시트 생성 + 채점.

지금까지의 수치(ΔE·color hit)는 **색**이 맞는지만 본다. "디자인이 비슷한가"는 범주 라벨이
없어 기계로 잴 수 없으므로, 소량을 사람이 직접 보고 판정한다. 이 스크립트가 그 두 단계를 맡는다.

  1) 시트 생성:  python scripts/review_nail_retrieval.py --make --samples 30
       → docs/nail_retrieval_review.html (자체 완결 HTML, 썸네일 내장)
         브라우저로 열어 "비슷함"을 체크하고 [CSV 저장] 클릭
  2) 채점:       python scripts/review_nail_retrieval.py --score <내려받은.csv>
       → precision@1 / precision@5 / MRR

질의는 인덱스 안 크롭에서 뽑되, **같은 사진(디자인ID)에서 나온 후보는 전부 제외**한다
(같은 발의 다른 발톱을 맞히는 건 자명하므로). eval_nail_retrieval.py 와 같은 규약이다.
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import sys
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
INDEX_DIR = PROJECT_ROOT / "data" / "nail_index"
OUT_HTML = PROJECT_ROOT / "docs" / "nail_retrieval_review.html"

MIN_CHROMA = 15.0   # 민낯·클리어는 '디자인'으로 보기 어려워 질의에서 뺀다


def load_index():
    emb = np.load(INDEX_DIR / "embeddings.npy")
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    if len(emb) != len(meta):
        raise SystemExit(f"인덱스 불일치: embeddings {len(emb)} vs meta {len(meta)}")
    return emb, meta


def chroma(lab) -> float:
    return (lab[1] ** 2 + lab[2] ** 2) ** 0.5


def thumb_uri(index_dir: Path, item_id: str) -> str:
    path = index_dir / "thumbs" / f"{item_id}.png"
    if not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def make_sheet(samples: int, topk: int, color_weight: float, seed: int) -> int:
    from app.core.config import get_settings  # noqa: F401  (설정 로드 확인용)

    emb, meta = load_index()
    labs = np.array([m["color_lab"] for m in meta], dtype=np.float32)
    designs = np.array([m["design_id"] for m in meta])

    pool = [i for i, m in enumerate(meta) if chroma(m["color_lab"]) >= MIN_CHROMA]
    if not pool:
        raise SystemExit("채도 조건을 만족하는 크롭이 없습니다.")
    rng = np.random.default_rng(seed)
    queries = rng.choice(pool, size=min(samples, len(pool)), replace=False)

    rows_html = []
    for qi in queries:
        qi = int(qi)
        scores = emb @ emb[qi]
        if color_weight:
            scores = scores - color_weight * (np.linalg.norm(labs - labs[qi], axis=1) / 100.0)
        scores[designs == designs[qi]] = -np.inf
        top = np.argsort(scores)[::-1][:topk]

        q = meta[qi]
        cards = []
        for rank, mi in enumerate(top, start=1):
            m = meta[int(mi)]
            uri = thumb_uri(INDEX_DIR, m["id"])
            cards.append(f"""
      <label class="cand">
        <img src="{uri}" alt="{html.escape(m['id'])}">
        <span class="cap">#{rank} · {html.escape(m['region'])} · ΔE {np.linalg.norm(np.asarray(m['color_lab']) - np.asarray(q['color_lab'])):.0f}</span>
        <input type="checkbox" data-q="{html.escape(q['id'])}" data-m="{html.escape(m['id'])}" data-rank="{rank}">
      </label>""")

        rows_html.append(f"""
  <section class="row">
    <div class="query">
      <img src="{thumb_uri(INDEX_DIR, q['id'])}" alt="query">
      <span class="cap">질의 · {html.escape(q['region'])}<br>{html.escape(q['design_id'])}</span>
    </div>
    <div class="cands">{''.join(cards)}</div>
  </section>""")

    doc = f"""<!doctype html>
<meta charset="utf-8">
<title>네일 리트리벌 리뷰 ({len(queries)}건)</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 24px; background:#fafafa; }}
 h1 {{ font-size: 20px; }}
 .hint {{ color:#555; line-height:1.6; margin-bottom:16px; }}
 .row {{ display:flex; gap:16px; align-items:flex-start; padding:12px;
        background:#fff; border:1px solid #e3e3e3; border-radius:8px; margin-bottom:12px; }}
 .query {{ text-align:center; }}
 .query img {{ width:96px; height:96px; border-radius:6px; border:2px solid #333; }}
 .cands {{ display:flex; gap:12px; flex-wrap:wrap; }}
 .cand {{ text-align:center; cursor:pointer; }}
 .cand img {{ width:80px; height:80px; border-radius:6px; border:1px solid #ccc; display:block; }}
 .cand input {{ margin-top:4px; transform:scale(1.3); }}
 .cap {{ display:block; font-size:11px; color:#666; margin-top:4px; }}
 button {{ position:sticky; bottom:16px; padding:10px 18px; font-size:15px;
           background:#111; color:#fff; border:0; border-radius:6px; cursor:pointer; }}
</style>
<h1>네일 리트리벌 리뷰 — 질의 {len(queries)}건 × top-{topk}</h1>
<p class="hint">
 왼쪽(굵은 테두리)이 <b>질의</b>입니다. 오른쪽 후보 중 <b>디자인이 비슷하다고 느껴지는 것</b>에 체크하세요.<br>
 색만 같고 무늬가 전혀 다르면 체크하지 마세요. 판단이 애매하면 <b>체크하지 않습니다</b>(보수적으로).<br>
 다 하면 아래 버튼으로 CSV를 내려받아 <code>--score</code> 로 채점합니다.
</p>
{''.join(rows_html)}
<button onclick="save()">CSV 저장</button>
<script>
function save() {{
  const rows = [['query_id','match_id','rank','relevant']];
  document.querySelectorAll('input[type=checkbox]').forEach(cb => {{
    rows.push([cb.dataset.q, cb.dataset.m, cb.dataset.rank, cb.checked ? '1' : '0']);
  }});
  const csv = rows.map(r => r.join(',')).join('\\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], {{type:'text/csv'}}));
  a.download = 'nail_retrieval_review.csv';
  a.click();
}}
</script>
"""
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(doc, encoding="utf-8")
    print(f"리뷰 시트: {OUT_HTML}")
    print(f"  질의 {len(queries)}건 × top-{topk} · 채도 C*>={MIN_CHROMA:.0f} 크롭에서 추출")
    print(f"  크기 {OUT_HTML.stat().st_size/1048576:.1f} MB (썸네일 내장)")
    print("  브라우저로 열어 체크 → [CSV 저장] → --score 로 채점")
    return 0


def score(csv_path: Path) -> int:
    # utf-8-sig: 엑셀로 열었다 저장하면 BOM 이 붙어 첫 헤더가 '﻿query_id' 가 된다.
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    if not rows:
        raise SystemExit("빈 CSV 입니다.")
    required = {"query_id", "match_id", "rank", "relevant"}
    missing = required - set(rows[0])
    if missing:
        raise SystemExit(f"CSV 컬럼 누락: {sorted(missing)} (있는 컬럼: {sorted(rows[0])})")

    by_query: dict[str, list[tuple[int, bool]]] = {}
    for r in rows:
        by_query.setdefault(r["query_id"], []).append((int(r["rank"]), r["relevant"] == "1"))

    n = len(by_query)
    p_at_1 = hits_at_5 = 0
    precisions: list[float] = []
    rr: list[float] = []
    for _q, items in by_query.items():
        items.sort()
        rel = [ok for _rank, ok in items]
        if rel and rel[0]:
            p_at_1 += 1
        if any(rel[:5]):
            hits_at_5 += 1
        precisions.append(sum(rel[:5]) / max(len(rel[:5]), 1))
        first = next((i for i, ok in enumerate(rel, start=1) if ok), None)
        rr.append(1 / first if first else 0.0)

    print(f"\n=== 사람 판정 채점 (질의 {n}건) ===")
    print(f"precision@1        : {p_at_1 / n * 100:5.1f}%  (1순위가 비슷한 디자인)")
    print(f"hit@5              : {hits_at_5 / n * 100:5.1f}%  (top-5 안에 하나라도 비슷)")
    print(f"평균 precision@5   : {sum(precisions) / n * 100:5.1f}%  (top-5 중 비슷한 비율)")
    print(f"MRR                : {sum(rr) / n:5.3f}  (첫 정답 순위의 역수 평균)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--make", action="store_true", help="리뷰 시트 생성")
    ap.add_argument("--score", type=Path, default=None, help="채워진 CSV 로 채점")
    ap.add_argument("--samples", type=int, default=30)
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--color-weight", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.score:
        return score(args.score)
    if args.make:
        return make_sheet(args.samples, args.topk, args.color_weight, args.seed)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
