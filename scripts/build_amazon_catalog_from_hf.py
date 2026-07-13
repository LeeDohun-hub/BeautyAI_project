"""McAuley Amazon Reviews 2023(HuggingFace) Beauty 메타 → 아마존 카탈로그 보강.

왜: 안티봇 크롤/유료 API 없이, 공개 데이터셋으로 amazon.com 커버리지를 넓힌다. McAuley의
Beauty 카테고리 메타데이터(parent_asin + title + store(브랜드) + rating)는 지금 Kaggle 52k보다
훨씬 크다(All_Beauty 112k, Beauty_and_Personal_Care ~1M). parent_asin 으로 amazon.com/dp/
직링크를 만든다. 단 2023 스냅샷이라 최신품은 빠지고 US 중심(→ JP/신상은 별도 크롤 보완).

성능: match_amazon 은 카탈로그 전체를 선형 스캔하므로 1M을 통째로 넣으면 매칭이 크게 느려진다.
그래서 **우리 타깃 K/J-beauty 시드 브랜드(store 매칭)로 필터**해 관련 상품만 남긴다.

출력(loader 스키마 동일): data/manifests/amazon_beauty_hf.csv (asin,brand,title,stars,reviews,imageUrl)

Usage:
  # HF에서 자동 다운로드(캐시) 후 인제스트. 여러 카테고리 지정 가능.
  python scripts/build_amazon_catalog_from_hf.py --categories All_Beauty
  python scripts/build_amazon_catalog_from_hf.py --categories All_Beauty Beauty_and_Personal_Care
  # 이미 받은 로컬 jsonl 지정도 가능.
  python scripts/build_amazon_catalog_from_hf.py --files path/to/meta_All_Beauty.jsonl
  python scripts/build_amazon_catalog_from_hf.py ... --all-beauty   # 브랜드 필터 없이 전부(비권장)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

FIELDNAMES = ["asin", "brand", "title", "stars", "reviews", "imageUrl"]
_HF_REPO = "McAuley-Lab/Amazon-Reviews-2023"


def _seed_brand_keys() -> dict[str, str]:
    """정규화 브랜드키 → 대표 표기. store 문자열을 이 키들과 대조해 타깃 브랜드만 남긴다."""
    from app.services.amazon_catalog import _KO_TO_EN_BRAND
    from app.services.recommender import JBEAUTY_BRANDS, KBEAUTY_BRANDS

    out: dict[str, str] = {}
    for b in set(KBEAUTY_BRANDS) | set(JBEAUTY_BRANDS) | set(_KO_TO_EN_BRAND.values()):
        key = re.sub(r"[^a-z0-9]", "", b.lower())
        if len(key) >= 3:  # 1~2글자 키는 오매칭 위험(브랜드 게이트 교훈)
            out.setdefault(key, b)
    return out


def _store_brand(store: str, seed_keys: dict[str, str]) -> str | None:
    """store(브랜드)가 타깃 시드 브랜드에 해당하면 대표 표기를 돌려준다(아니면 None).

    store 예: 'Peripera', 'PERIPERA Official', 'espoir'. **부분문자열 매칭 금지** — 'hera'가
    'tHERApist'·'PantHERA'에 걸리는 오태깅(실측: hera 2332행 중 507행이 스프레이병/극세사천 등
    비-헤라)을 막는다. 브랜드 게이트와 동일 교훈. 매칭 조건: (1)정규화 전체 일치, (2)공백 토큰
    일치('HERA Official'→토큰 'hera'), (3)정규화 store가 키로 시작('heraofficial'→'hera'로 시작)."""
    lc = (store or "").lower()
    sk = re.sub(r"[^a-z0-9]", "", lc)
    if not sk:
        return None
    tokens = {re.sub(r"[^a-z0-9]", "", t) for t in lc.split()}
    tokens.discard("")
    for key, disp in seed_keys.items():
        if key == sk or key in tokens or sk.startswith(key):
            return disp
    return None


def _first_image(images) -> str:
    if isinstance(images, list):
        for im in images:
            if isinstance(im, dict):
                url = im.get("large") or im.get("hi_res") or im.get("thumb")
                if url:
                    return str(url)
    return ""


def _resolve_files(args) -> list[Path]:
    files = [Path(f) for f in (args.files or [])]
    if args.categories:
        from huggingface_hub import hf_hub_download
        for cat in args.categories:
            print(f"HF 다운로드/캐시: meta_{cat}.jsonl ...", flush=True)
            p = hf_hub_download(_HF_REPO, f"raw/meta_categories/meta_{cat}.jsonl", repo_type="dataset")
            files.append(Path(p))
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--categories", nargs="*", help="HF McAuley 카테고리명(예: All_Beauty Beauty_and_Personal_Care)")
    ap.add_argument("--files", nargs="*", help="로컬 meta_*.jsonl 경로(직접 지정)")
    ap.add_argument("--all-beauty", action="store_true", help="브랜드 필터 없이 전 상품(비권장: 매칭 느려짐)")
    ap.add_argument("--min-reviews", type=int, default=1, help="이 리뷰수 미만 제외(노이즈/죽은상품 감소)")
    ap.add_argument("--out", default=str(_ROOT / "data" / "manifests" / "amazon_beauty_hf.csv"))
    args = ap.parse_args()

    files = _resolve_files(args)
    if not files:
        print("ERROR: --categories 또는 --files 필요", file=sys.stderr)
        return 1

    seed_keys = _seed_brand_keys()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    kept = scanned = 0
    with out_path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDNAMES)
        writer.writeheader()
        for path in files:
            if not path.exists():
                print(f"  건너뜀(없음): {path}", file=sys.stderr)
                continue
            print(f"인제스트: {path.name}", flush=True)
            with path.open(encoding="utf-8", errors="ignore") as f:
                for line in f:
                    scanned += 1
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    asin = str(d.get("parent_asin") or "").strip()
                    title = str(d.get("title") or "").strip()
                    if not asin or not title or asin in seen:
                        continue
                    store = str(d.get("store") or "").strip()
                    if args.all_beauty:
                        brand = store
                    else:
                        brand = _store_brand(store, seed_keys)
                        if not brand:
                            continue  # 타깃 브랜드 아님 → 스킵(카탈로그 슬림/관련성 유지)
                    try:
                        reviews = int(d.get("rating_number") or 0)
                    except (TypeError, ValueError):
                        reviews = 0
                    if reviews < args.min_reviews:
                        continue
                    seen.add(asin)
                    writer.writerow({
                        "asin": asin,
                        "brand": brand or store,
                        "title": title[:300],
                        "stars": d.get("average_rating") or "",
                        "reviews": reviews,
                        "imageUrl": _first_image(d.get("images")),
                    })
                    kept += 1
    print(f"scanned {scanned} -> kept {kept} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
