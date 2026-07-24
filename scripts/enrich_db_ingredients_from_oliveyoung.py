"""성분이 비어 있는 DB 상품을 올리브영 KR 카탈로그에 매칭해 고시 전성분을 채운다.

enrich_ingredients_oliveyoung.py 와 다른 점: 저쪽은 product_url 에서 goodsNo 를 뽑는다.
여기서는 **이름 매칭**으로 goodsNo 를 찾는다. 같은 상품이라도 우리 DB 링크가 아마존·
마츠키요일 수 있어서(리전별 카탈로그) URL 만으로는 goodsNo 를 못 얻기 때문이다.

매칭은 런타임 버튼이 쓰는 것과 같은 로직(oliveyoung_kr_search.match_kr_catalog, 최소 점수
0.5)을 재사용한다. 별도 기준을 만들면 버튼과 성분이 서로 다른 상품을 가리킬 수 있다.

실측(2026-07-24): 성분 없는 1,297건 중 136건이 매칭됐다. 나머지는 아마존/세포라의 미국
상품이라 한국 카탈로그에 아예 없다.

Usage:
    python scripts/enrich_db_ingredients_from_oliveyoung.py --dry-run
    python scripts/enrich_db_ingredients_from_oliveyoung.py --sqlite
    BODY_LOAD_CONFIRM=yes python scripts/enrich_db_ingredients_from_oliveyoung.py
"""
from __future__ import annotations

import argparse

import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

# reconfigure 를 쓴다. sys.stdout 을 TextIOWrapper 로 '교체'하면, 같은 짓을 하는 모듈을
# import 할 때 이중 래핑이 되고 먼저 만든 래퍼가 GC 되면서 버퍼를 닫아버린다
# (ValueError: I/O operation on closed file).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.services.ingredient_aliases import detect_ingredients_ko  # noqa: E402
from enrich_ingredients_oliveyoung import fetch_notice, parse_notice_ingredients  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", action="store_true", help="로컬 beautyai.db 사용")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 집계만")
    parser.add_argument("--limit", type=int, default=0, help="처리 최대 건수(0=전부)")
    # 0.8s 로는 ~60건에서 스로틀에 걸린다(실측). 2.5s 가 안전선.
    parser.add_argument("--delay", type=float, default=2.5)
    args = parser.parse_args()

    if args.sqlite:
        os.environ["DATABASE_URL"] = f"sqlite:///{(PROJECT_ROOT / 'beautyai.db').as_posix()}"

    from curl_cffi import requests as creq  # noqa: E402
    from sqlalchemy.orm import selectinload  # noqa: E402

    from app.core.database import SessionLocal, database_url  # noqa: E402
    from app.models import Ingredient, Product, ProductIngredient  # noqa: E402
    from app.services.oliveyoung_kr_search import match_kr_catalog  # noqa: E402
    from load_product_catalog_to_db import ensure_ingredient, infer_skin_types  # noqa: E402

    print(f"대상 DB: {database_url.split('@')[-1]}")
    if not args.sqlite and not args.dry_run and not database_url.startswith("sqlite"):
        if os.environ.get("BODY_LOAD_CONFIRM") != "yes":
            raise SystemExit("원격 DB 수정에는 BODY_LOAD_CONFIRM=yes 가 필요합니다. (--dry-run 으로 미리보기)")

    db = SessionLocal()
    try:
        ingredient_cache = {i.name: i for i in db.query(Ingredient).all()}
        products = (
            db.query(Product)
            .options(selectinload(Product.brand), selectinload(Product.ingredients))
            .filter(~Product.ingredients.any())
            .all()
        )
        print(f"성분 없는 상품: {len(products)}건")

        pairs = []
        for product in products:
            match = match_kr_catalog(product.brand.name if product.brand else "", product.name or "")
            if match:
                pairs.append((product, match.goods_no))
        print(f"KR 카탈로그 매칭: {len(pairs)}건")
        if args.limit:
            pairs = pairs[:args.limit]

        session = creq.Session()
        filled = empty = failed = 0
        consecutive_bad = 0
        detected_counts: Counter[str] = Counter()
        samples: list[str] = []
        for index, (product, goods_no) in enumerate(pairs, 1):
            # 스로틀링이 'HTTP 200 + 빈 고시'로 위장하므로 빈 응답은 재시도한다.
            blob = ""
            http_ok = False
            for attempt in range(3):
                html = fetch_notice(session, goods_no)
                if html is None:
                    time.sleep(5 * (attempt + 1))
                    continue
                http_ok = True
                blob = parse_notice_ingredients(html)
                if blob:
                    break
                time.sleep(5 * (attempt + 1))

            if not http_ok:
                failed += 1
                consecutive_bad += 1
            elif blob:
                names = detect_ingredients_ko(blob)
                if names:
                    for name in names:
                        ingredient = ensure_ingredient(db, ingredient_cache, name)
                        db.add(ProductIngredient(product=product, ingredient=ingredient, weight=1.0))
                    product.skin_types = infer_skin_types(names)
                    filled += 1
                    detected_counts.update(names)
                    if len(samples) < 6:
                        samples.append(f"[{product.category}] {product.name[:44]} -> {names}")
                else:
                    empty += 1  # 전성분은 받았으나 우리 14종에 해당 없음
                consecutive_bad = 0
            else:
                empty += 1
                consecutive_bad += 1

            if consecutive_bad >= 6:
                print("연속 실패/빈응답 6건(레이트리밋 추정). 여기까지 저장하고 중단합니다.")
                break
            if index % 25 == 0:
                print(f"  {index}/{len(pairs)} · 성분 채움 {filled} · 해당없음 {empty} · 실패 {failed}", flush=True)
            time.sleep(args.delay + random.uniform(0, args.delay * 0.5))

        if args.dry_run:
            db.rollback()
            print("(dry-run — 롤백함)")
        else:
            db.commit()

        print(f"\n성분 채운 상품: {filled}건 · 전성분에 해당 성분 없음: {empty}건 · 요청 실패: {failed}건")
        if detected_counts:
            print("검출 성분:", dict(detected_counts.most_common(8)))
        for sample in samples:
            print(f"  {sample}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
