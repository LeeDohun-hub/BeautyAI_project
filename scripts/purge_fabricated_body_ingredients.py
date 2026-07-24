"""폐기된 load_body_products.py 가 지어낸 성분 링크를 제거한다.

배경: 옛 로더는 성분이 검출되지 않으면 이렇게 채워 넣었다.

    ingredient_names = ["Panthenol", "Ceramide"] if category in {"body_lotion", "body_cream", "body_oil"} else []

그 결과 운영 DB에 옛 밑줄식 바디 카테고리 상품 988건 중 815건이 정확히
(Ceramide, Panthenol) 두 개만 갖고 있다. 아무도 확인한 적 없는 성분 주장이다.

왜 지금 지워야 하나: 새 바디 추천은 avoid 목록이 있는 질환(습진·아토피)에서 '성분이
확인된 상품만' 쓴다(strict). 조작 성분도 '확인된 것'으로 보이므로 그대로 두면 추천에
올라가면서 이유에 "Ceramide 함유"라고 표시된다. 실제 성분을 모르니 자극 성분 배제도
무의미해진다.

처리 방식: 링크를 지운 뒤 **상품명에서 다시 검출해 근거 있는 것만 복원**한다.
이름에 실제로 'Ceramide'가 든 제품까지 잃지 않으려는 것.

Usage:
    python scripts/purge_fabricated_body_ingredients.py --dry-run
    BODY_LOAD_CONFIRM=yes python scripts/purge_fabricated_body_ingredients.py
    python scripts/purge_fabricated_body_ingredients.py --sqlite
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# 옛 로더가 쓰던 밑줄식 카테고리.
LEGACY_BODY_CATEGORIES = [
    "body_lotion", "body_cream", "body_oil", "body_wash", "body_scrub",
]
# 옛 로더 폴백의 시그니처.
FABRICATED_SIGNATURE = ("Ceramide", "Panthenol")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", action="store_true", help="로컬 beautyai.db 사용")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 집계만")
    args = parser.parse_args()

    if args.sqlite:
        os.environ["DATABASE_URL"] = f"sqlite:///{(PROJECT_ROOT / 'beautyai.db').as_posix()}"

    from sqlalchemy.orm import selectinload  # noqa: E402

    from app.core.database import SessionLocal, database_url  # noqa: E402
    from app.models import Brand, Product, ProductIngredient  # noqa: E402
    from load_product_catalog_to_db import detect_ingredients, ensure_ingredient  # noqa: E402
    from app.models import Ingredient  # noqa: E402

    print(f"대상 DB: {database_url.split('@')[-1]}")
    if not args.sqlite and not args.dry_run and not database_url.startswith("sqlite"):
        if os.environ.get("BODY_LOAD_CONFIRM") != "yes":
            raise SystemExit(
                "원격 DB를 수정하려면 BODY_LOAD_CONFIRM=yes 를 명시해야 합니다.\n"
                "미리보기는 --dry-run 을 쓰세요."
            )

    db = SessionLocal()
    try:
        ingredient_cache = {i.name: i for i in db.query(Ingredient).all()}
        products = (
            db.query(Product)
            .options(
                selectinload(Product.brand),
                selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
            )
            .filter(Product.category.in_(LEGACY_BODY_CATEGORIES))
            .all()
        )
        print(f"옛 밑줄식 바디 카테고리 상품: {len(products)}건")

        purged = restored = 0
        restored_counts: Counter[str] = Counter()
        samples: list[str] = []
        for product in products:
            current = tuple(sorted(pi.ingredient.name for pi in product.ingredients))
            if current != FABRICATED_SIGNATURE:
                continue
            # 이름에서 실제로 검출되는 성분만 남긴다(근거 있는 것은 잃지 않는다).
            from_name = detect_ingredients(product.name or "", "")
            for link in list(product.ingredients):
                db.delete(link)
            db.flush()
            purged += 1
            if from_name:
                for name in from_name:
                    ingredient = ensure_ingredient(db, ingredient_cache, name)
                    db.add(ProductIngredient(product=product, ingredient=ingredient, weight=1.0))
                restored += 1
                restored_counts.update(from_name)
                if len(samples) < 6:
                    samples.append(f"{product.brand.name} {product.name[:50]} -> {from_name}")

        if args.dry_run:
            db.rollback()
            print("(dry-run — 롤백함)")
        else:
            db.commit()

        print(f"\n조작 성분 제거: {purged}건")
        print(f"  그중 상품명 근거로 복원: {restored}건 {dict(restored_counts)}")
        print(f"  성분 미상으로 전환: {purged - restored}건 "
              f"(질환 추천 strict 모드에서 자동 제외됨)")
        if samples:
            print("\n복원 예:")
            for sample in samples:
                print(f"  {sample}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
