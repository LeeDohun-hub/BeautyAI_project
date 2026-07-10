"""Kaggle Amazon(US) 1.4M 상품 데이터셋 → Beauty 카탈로그 매니페스트.

목적: KR 아이템매칭의 amazon.com 버튼을 '검색 링크'(투기) 대신 '검증된 ASIN 직링크'로 만든다.
글로벌 브랜드는 amazon.com/amazon.co.jp가 같은 ASIN을 공유하는 경우가 많아, 같은 ASIN을
amazon.co.jp/dp/{asin} 로 치환하면 JP 데이터셋 없이 일본 아마존 상품 페이지로도 연결된다
(공유 ASIN이 아니면 404 — 블라인드 검색보다는 타겟됨).

입력: Kaggle 'asaniczka/amazon-products-dataset-2023-1-4m-products'의 amazon_products.csv
      (컬럼: asin,title,imgUrl,productURL,stars,reviews,price,listPrice,category_id,...)
      + amazon_categories.csv (id,category_name)
출력: data/manifests/amazon_beauty_products.csv (asin,brand,title,stars,reviews,imageUrl)

Usage:
  python scripts/build_amazon_beauty_catalog.py --src <다운로드폴더> [--min-reviews 0]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# Beauty & Personal Care 하위 카테고리(amazon_categories.csv 기준).
BEAUTY_CATEGORY_IDS = {"45", "46", "47", "48", "49", "50", "51", "53"}

FIELDNAMES = ["asin", "brand", "title", "stars", "reviews", "imageUrl"]

# 타이틀 앞머리에서 브랜드 추정: 대문자/브랜드형 토큰 1~2개. 정밀하진 않지만 매칭 보조용.
_BRAND_STOP = {"the", "new", "for", "womens", "mens", "kids", "pack", "of", "set"}


def _guess_brand(title: str) -> str:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9&'.+-]*", title or "")
    picked: list[str] = []
    for tok in tokens[:3]:
        if tok.lower() in _BRAND_STOP:
            break
        picked.append(tok)
        # 소문자로 시작하는 일반명사가 나오면 브랜드 끝(예: 'COSRX aha ...').
        if len(picked) >= 1 and tok[0].islower():
            break
        if len(picked) >= 2:
            break
    return " ".join(picked)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="amazon_products.csv / amazon_categories.csv 가 있는 폴더")
    ap.add_argument("--min-reviews", type=int, default=0, help="이 리뷰수 미만 상품 제외(노이즈 감소)")
    ap.add_argument("--out", default=str(_ROOT / "data" / "manifests" / "amazon_beauty_products.csv"))
    args = ap.parse_args()

    src = Path(args.src)
    products_csv = src / "amazon_products.csv"
    if not products_csv.exists():
        print(f"ERROR: {products_csv} 없음", file=sys.stderr)
        return 1

    kept = 0
    total = 0
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with products_csv.open(encoding="utf-8", errors="ignore", newline="") as f, \
         out_path.open("w", encoding="utf-8", newline="") as out:
        reader = csv.DictReader(f)
        writer = csv.DictWriter(out, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in reader:
            total += 1
            if str(row.get("category_id") or "").strip() not in BEAUTY_CATEGORY_IDS:
                continue
            asin = str(row.get("asin") or "").strip()
            title = str(row.get("title") or "").strip()
            if not asin or not title:
                continue
            try:
                reviews = int(float(row.get("reviews") or 0))
            except ValueError:
                reviews = 0
            if reviews < args.min_reviews:
                continue
            writer.writerow({
                "asin": asin,
                "brand": _guess_brand(title),
                "title": title,
                "stars": row.get("stars") or "",
                "reviews": reviews,
                "imageUrl": row.get("imgUrl") or "",
            })
            kept += 1

    print(f"scanned {total} products -> kept {kept} beauty products -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
