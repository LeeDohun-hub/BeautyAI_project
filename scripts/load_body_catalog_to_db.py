"""data/manifests/body_products.csv 를 상품 DB에 적재한다.

기존 load_body_products.py 를 대체한다. 달라진 점 두 가지:

1. **성분을 지어내지 않는다.** 옛 로더는 성분이 안 잡히면 ["Panthenol", "Ceramide"]를
   그냥 박아 넣었다. 그러면 추천 이유에 "2개 바디 진정 성분"이라고 표시되는데 그 제품이
   실제로 두 성분을 가졌는지 아무도 확인한 적이 없다. 여기서는 이름에서 검출된 성분만
   붙이고, 없으면 성분 없이 적재한다(카탈로그로는 유효, 성분 기반 추천에는 미노출).

2. **네임스페이스 카테고리로 적재한다.** body.* / hand.* / foot.* 라서 얼굴 카테고리
   (cream, lotion, ...)와 문자열이 절대 겹치지 않는다.

이미 다른 로더가 넣어둔 동일 상품은 새로 만들지 않고 카테고리만 바로잡는다.

Usage:
    python scripts/load_body_catalog_to_db.py --sqlite
    python scripts/load_body_catalog_to_db.py            # DATABASE_URL 사용
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.services.body_categories import ALL_CATEGORIES, group_of  # noqa: E402

# 옛 제너릭 임포터가 남긴 카테고리. 새 네임스페이스로 옮겨 애매한 중간 상태를 없앤다.
LEGACY_CATEGORY_MAP = {
    "body moisturizers": "body.lotion",
    "bath & shower": "body.wash",
}

# products.name 은 varchar(180). 아마존 타이틀은 SEO 키워드가 붙어 이걸 넘는다.
NAME_LIMIT = 180
BRAND_LIMIT = 120


def shorten_name(name: str) -> str:
    """180자 제한에 맞춰 자른다. 구분자에서 끊어 상품명이 말이 되게 남긴다."""
    if len(name) <= NAME_LIMIT:
        return name
    head = name[:NAME_LIMIT]
    for delimiter in ("|", " - ", " – ", ",", " ", "、", "｜"):
        cut = head.rfind(delimiter)
        if cut > NAME_LIMIT // 2:
            return head[:cut].strip()
    return head.strip()


def load_kr_ingredients() -> dict[str, list[str]]:
    """올리브영 고시에서 뽑아둔 전성분(goodsNo → 표준 성분명)을 읽는다.

    enrich_ingredients_oliveyoung.py 의 산출물. 없으면 빈 dict — 이름 기반 검출로만 간다.

    저장된 ``detected`` 컬럼을 믿지 않고 원본 ``ingredients_ko`` 에서 매번 다시 검출한다.
    별칭 테이블을 고쳤을 때(예: 레티노이드 에스터 누락 수정) 재크롤 없이 반영되게 하려는 것.
    """
    from app.services.ingredient_aliases import detect_ingredients_ko

    path = PROJECT_ROOT / "data" / "manifests" / "oliveyoung_kr_ingredients.csv"
    if not path.exists():
        return {}
    table: dict[str, list[str]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            detected = detect_ingredients_ko(row.get("ingredients_ko") or "")
            if detected:
                table[row["goodsNo"]] = detected
    return table


def load_jp_ingredients() -> dict[str, list[str]]:
    """라쿠텐 itemCaption 에서 뽑아둔 JP 전성분(key → 표준 성분명).

    enrich_ingredients_rakuten.py 의 산출물. 키는 거기서 만든 ``source|name[:120]`` 이다.
    KR 고시와 마찬가지로 원본에서 매번 다시 검출한다(별칭 수정이 재크롤 없이 반영되게).
    """
    from app.services.ingredient_aliases import detect_ingredients_ja

    path = PROJECT_ROOT / "data" / "manifests" / "rakuten_jp_ingredients.csv"
    if not path.exists():
        return {}
    table: dict[str, list[str]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            detected = detect_ingredients_ja(row.get("ingredients_ja") or "")
            if detected:
                table[row["key"]] = detected
    return table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifests/body_products.csv")
    parser.add_argument("--sqlite", action="store_true", help="로컬 beautyai.db 사용")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 집계만")
    args = parser.parse_args()

    # DATABASE_URL 은 app.core.database 를 import 하는 순간 engine 에 굳는다.
    # 반드시 import 전에 설정해야 --sqlite 가 듣는다.
    if args.sqlite:
        os.environ["DATABASE_URL"] = f"sqlite:///{(PROJECT_ROOT / 'beautyai.db').as_posix()}"

    from app.core.database import Base, SessionLocal, database_url, engine  # noqa: E402
    from app.models import Brand, Ingredient, Product, ProductIngredient  # noqa: E402
    from load_product_catalog_to_db import (  # noqa: E402
        detect_ingredients,
        ensure_ingredient,
        infer_skin_types,
    )

    target = database_url.split("@")[-1]
    print(f"대상 DB: {target}")
    if not args.sqlite and not args.dry_run and not database_url.startswith("sqlite"):
        confirm = os.environ.get("BODY_LOAD_CONFIRM", "")
        if confirm != "yes":
            raise SystemExit(
                "원격 DB에 쓰려면 BODY_LOAD_CONFIRM=yes 를 명시해야 합니다.\n"
                "로컬 검증은 --sqlite, 미리보기는 --dry-run 을 쓰세요."
            )

    manifest_path = PROJECT_ROOT / args.manifest
    if not manifest_path.exists():
        raise SystemExit(
            f"매니페스트가 없습니다: {manifest_path}\n"
            "먼저 실행: python scripts/build_body_catalog.py"
        )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        brand_cache = {b.name: b for b in db.query(Brand).all()}
        ingredient_cache = {i.name: i for i in db.query(Ingredient).all()}
        existing: dict[tuple[str, str], Product] = {}
        for product in db.query(Product).join(Brand).all():
            existing[((product.brand.name or "").lower(), (product.name or "").lower())] = product

        # 1) 옛 카테고리 정리
        migrated = 0
        for product in list(existing.values()):
            target = LEGACY_CATEGORY_MAP.get((product.category or "").strip().lower())
            if target:
                product.category = target
                migrated += 1

        # 2) 매니페스트 적재
        kr_ingredients = load_kr_ingredients()
        jp_ingredients = load_jp_ingredients()
        print(f"올리브영 고시 전성분: {len(kr_ingredients)}건 · 라쿠텐 전성분: {len(jp_ingredients)}건 로드")
        inserted = updated = skipped = 0
        no_ingredient = from_notice = from_rakuten = 0
        by_category: Counter[str] = Counter()
        with manifest_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                category = (row.get("category") or "").strip()
                if category not in ALL_CATEGORIES:
                    skipped += 1
                    continue
                brand_name = ((row.get("brand") or "").strip() or "Unknown")[:BRAND_LIMIT]
                name = shorten_name((row.get("name") or "").strip())
                if not name:
                    skipped += 1
                    continue

                # 성분 출처 우선순위: 올리브영 고시 전성분(법정 표시) > 상품명 추론.
                # 고시는 상품명에 없는 성분까지 준다(아비브 핸드크림 → 판테놀·토코페롤).
                ingredient_names: list[str] = []
                goods_match = re.search(r"goodsNo=(\w+)", row.get("product_url") or "")
                if goods_match:
                    ingredient_names = list(kr_ingredients.get(goods_match.group(1), []))
                from_notice_hit = bool(ingredient_names)
                if from_notice_hit:
                    from_notice += 1
                elif row.get("region") == "jp":
                    # JP 는 라쿠텐 itemCaption 의 정식 전성분 블록(原料・成分等【成分】…).
                    jp_name = (row.get("name_ja") or row.get("name") or "").strip()
                    jp_key = f"{row.get('source')}|{jp_name[:120]}"
                    ingredient_names = list(jp_ingredients.get(jp_key, []))
                    if ingredient_names:
                        from_rakuten += 1
                        from_notice_hit = True  # 권위 있는 출처 → 기존 링크를 갈아끼운다
                else:
                    names_blob = " ".join(
                        filter(None, [name, row.get("name_ko") or "", row.get("name_ja") or ""])
                    )
                    ingredient_names = detect_ingredients(names_blob, "")
                if not ingredient_names:
                    no_ingredient += 1

                key = (brand_name.lower(), name.lower())
                product = existing.get(key)
                if product is not None:
                    # 이미 있는 상품이면 카테고리만 바로잡고 빈 필드를 채운다.
                    product.category = category
                    product.product_url = product.product_url or (row.get("product_url") or "")
                    product.image_url = product.image_url or (row.get("image_url") or "")
                    # 고시 전성분은 법정 표시라 이름 추론보다 권위가 있다. 있으면 기존
                    # 연결을 갈아끼운다(별칭 테이블을 고쳤을 때 반영되려면 필수 —
                    # 레티노이드 에스터 누락처럼 빠졌던 성분이 나중에 잡힌다).
                    # 고시가 없으면 기존 판정을 건드리지 않는다.
                    if ingredient_names and (from_notice_hit or not product.ingredients):
                        if product.ingredients:
                            for link in list(product.ingredients):
                                db.delete(link)
                            db.flush()
                        for ingredient_name in ingredient_names:
                            ingredient = ensure_ingredient(db, ingredient_cache, ingredient_name)
                            db.add(ProductIngredient(product=product, ingredient=ingredient, weight=1.0))
                        product.skin_types = infer_skin_types(ingredient_names)
                    updated += 1
                    by_category[category] += 1
                    continue

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
                    skin_types=infer_skin_types(ingredient_names) if ingredient_names else "all",
                    price=int(row.get("price") or 0),
                    description=f"{group_of(category)} care product ({row.get('source')})",
                    product_url=(row.get("product_url") or "")[:500],
                    image_url=(row.get("image_url") or "")[:500],
                    avg_rating=float(row.get("rating") or 0),
                    review_count=int(row.get("review_count") or 0),
                )
                db.add(product)
                db.flush()
                for ingredient_name in ingredient_names:
                    ingredient = ensure_ingredient(db, ingredient_cache, ingredient_name)
                    db.add(ProductIngredient(product=product, ingredient=ingredient, weight=1.0))
                existing[key] = product
                inserted += 1
                by_category[category] += 1

        if args.dry_run:
            db.rollback()
            print("(dry-run — 롤백함)")
        else:
            db.commit()

        total = inserted + updated
        print(f"신규 {inserted}건 · 기존 갱신 {updated}건 · 건너뜀 {skipped}건")
        print(f"옛 카테고리 이관: {migrated}건")
        print(f"성분 출처 — 올리브영 고시: {from_notice}건 · 라쿠텐 전성분: {from_rakuten}건 · "
              f"상품명 추론: {total - from_notice - from_rakuten - no_ingredient}건 · "
              f"미검출: {no_ingredient}건")
        print(f"성분 보유율: {(total - no_ingredient) * 100 // max(total, 1)}%")
        print("\n카테고리별:")
        for category, count in by_category.most_common():
            print(f"  {count:5d}  {category}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
