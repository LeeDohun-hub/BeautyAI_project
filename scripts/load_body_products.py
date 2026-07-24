"""[폐기됨 2026-07-24] scripts/load_body_catalog_to_db.py 를 쓸 것.

이 스크립트를 돌리지 말 것. 두 가지 이유로 대체됐다(docs/BODY_CATEGORY_SPEC.md 참조):

1. **성분을 지어낸다.** 아래 116행에서 성분이 검출되지 않으면 ["Panthenol", "Ceramide"]를
   그냥 채워 넣는다. 그러면 추천 이유에 "2개 바디 진정 성분"이라고 표시되는 제품이 실제로
   그 성분을 가졌는지 아무도 확인한 적이 없게 된다.
2. **이름에 'body'가 든 것만 찾는다.** 그래서 ILLIYOON 세라마이드 아토로션 같은 대표
   바디 상품을 놓친다(올리브영 공식 Bath & Body 106건 중 55건 누락, 실측).
   또 소스인 candidates.csv 에는 구매 링크·이미지·가격이 아예 없다.

대체 경로:
  python scripts/build_body_catalog.py          # 전 소스 → data/manifests/body_products.csv
  python scripts/load_body_catalog_to_db.py --sqlite

---
원문: Load body-care products from the catalog candidates CSV into the product DB.

This loader keeps body care separate from the generic skincare importer because
the generic category inference maps many body lotions/creams into face-care
categories.

Usage:
  python scripts/load_body_products.py --limit 800
  python scripts/load_body_products.py --limit 800 --sqlite
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from load_product_catalog_to_db import (  # noqa: E402
    clean_brand,
    clean_name,
    detect_ingredients,
    ensure_ingredient,
    infer_product_url,
    infer_skin_types,
    normalize_text,
    parse_float,
    parse_int,
    parse_ingredient_blob,
    parse_price,
)

BODY_TYPES = [
    ("body_wash", r"body\s*wash|shower\s*(gel|cream|oil|milk)|body\s*cleanser|body\s*shampoo|bath\s*(gel|soak|milk)"),
    ("body_scrub", r"body\s*scrub|body\s*polish|body\s*exfoliat|salt\s*scrub|sugar\s*scrub"),
    ("body_oil", r"body\s*oil|dry\s*body\s*oil|massage\s*oil"),
    ("body_cream", r"body\s*butter|body\s*cream|body\s*balm"),
    ("body_lotion", r"body\s*lotion|body\s*milk|body\s*(moistur|serum|essence)|hand\s*(&|and)\s*body"),
]
HAS_BODY = re.compile(r"\bbody\b|shower|bath\b", re.I)
EXCLUDE = re.compile(
    r"hair|shampoo|conditioner|mousse|hairspray|perfume|fragrance|body\s*mist|body\s*spray|"
    r"cologne|eau\s*de|palette|lipstick|mascara|foundation|nail|deodorant|toothpaste|mouth|wax\b|"
    r"pigment|glitter|shimmer\s*for",
    re.I,
)


def body_category(name: str) -> str | None:
    text = name.lower()
    if EXCLUDE.search(text):
        return None
    for category, pattern in BODY_TYPES:
        if re.search(pattern, text):
            return category
    if HAS_BODY.search(text) and re.search(r"lotion|cream|milk|butter|balm|oil|moistur", text):
        return "body_lotion"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="data/manifests/product_catalog_candidates.csv")
    parser.add_argument("--limit", type=int, default=800)
    parser.add_argument("--batch-size", type=int, default=300)
    parser.add_argument("--sqlite", action="store_true", help="Load into local beautyai.db.")
    args = parser.parse_args()

    if args.sqlite:
        os.environ["DATABASE_URL"] = f"sqlite:///{(PROJECT_ROOT / 'beautyai.db').as_posix()}"

    from app.core.database import Base, SessionLocal, engine  # noqa: E402
    from app.models import Brand, Ingredient, Product, ProductIngredient  # noqa: E402

    catalog_path = PROJECT_ROOT / args.catalog
    if not catalog_path.exists():
        raise SystemExit(f"Catalog not found: {catalog_path}")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    brand_cache = {brand.name: brand for brand in db.query(Brand).all()}
    ingredient_cache = {ingredient.name: ingredient for ingredient in db.query(Ingredient).all()}
    seen = {
        (product.brand.name.lower(), product.name.lower())
        for product in db.query(Product).join(Brand).all()
    }

    imported = 0
    scanned = 0
    fallback_rows = 0
    category_counts: Counter[str] = Counter()
    try:
        with catalog_path.open(encoding="utf-8", errors="ignore", newline="") as file:
            for row in csv.DictReader(file):
                scanned += 1
                name = clean_name(row.get("name", ""))
                if not name:
                    continue
                category = body_category(name)
                if not category:
                    continue
                brand_name = clean_brand(row.get("brand", ""))
                key = (brand_name.lower(), name.lower())
                if key in seen:
                    continue

                ingredient_blob = parse_ingredient_blob(row.get("ingredients", ""))
                ingredient_names = detect_ingredients(name, ingredient_blob)
                if not ingredient_names:
                    ingredient_names = ["Panthenol", "Ceramide"] if category in {"body_lotion", "body_cream", "body_oil"} else []
                    fallback_rows += 1
                if not ingredient_names:
                    continue
                seen.add(key)

                brand = brand_cache.get(brand_name)
                if brand is None:
                    brand = Brand(name=brand_name, description=f"{brand_name} body care source")
                    db.add(brand)
                    db.flush()
                    brand_cache[brand_name] = brand

                product = Product(
                    brand=brand,
                    name=name,
                    category=category,
                    skin_types=infer_skin_types(ingredient_names),
                    price=parse_price(row.get("price", "")),
                    description="Imported body-care product",
                    product_url=infer_product_url(row, brand_name, name),
                    image_url=normalize_text(row.get("image_url", "")),
                    avg_rating=parse_float(row.get("rating", "")),
                    review_count=parse_int(row.get("review_count", "")),
                )
                db.add(product)
                db.flush()
                for ingredient_name in ingredient_names:
                    ingredient = ensure_ingredient(db, ingredient_cache, ingredient_name)
                    db.add(ProductIngredient(product=product, ingredient=ingredient, weight=1.0))
                imported += 1
                category_counts[category] += 1
                if imported % args.batch_size == 0:
                    db.commit()
                    print(f"imported={imported} scanned={scanned}", flush=True)
                if imported >= args.limit:
                    break
        db.commit()
    finally:
        db.close()

    print(f"\nImported {imported} body products (scanned {scanned}).")
    print("Category counts:", dict(category_counts))
    print(f"Fallback ingredient rows: {fallback_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
