"""KR 지역 상품을 네이버 쇼핑 데이터로 한글화(퍼스널컬러 방식 채용).

스킨케어 카탈로그 상품은 영문 브랜드/상품명(예: 'CeraVe Moisturizing Cream')이라
한국 플랫폼(올리브영 국내몰 등) 검색이 약하다. KR 지역에서는 각 상품을 네이버 쇼핑에서
'영문 브랜드+상품명'으로 조회해(네이버는 이 쿼리로 잘 매칭됨) 상위 일치 상품의
**한글 브랜드/상품명 + 실제 네이버 URL/이미지**로 카드를 채운다. 이후 올리브영 등의
검색 링크는 이 한글명으로 만들어져 훨씬 안전하게 조회된다(퍼스널컬러 카드와 동일한 방식).

정책:
- 네이버 'sort=sim' 상위 결과는 '브랜드+상품명' 특정 쿼리에서 해당 브랜드로 신뢰할 수 있다.
  따라서 상위 결과로 이름/URL/이미지를 채운다(퍼스널컬러도 네이버를 그대로 신뢰).
- 한글 브랜드는 결과의 brand 필드에서 취하되, 네이버가 브랜드를 못 줘서 채운 '네이버쇼핑'
  같은 정크값은 건너뛰고, 그마저 없으면 원래 영문 브랜드를 유지한다.
- 조회 결과가 없거나 네이버 키가 없으면 원문(영문) 카드를 그대로 둔다.
- 주의: 정확한 SKU가 네이버에 없으면 같은 브랜드의 가장 가까운 상품이 표시될 수 있다.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable
from urllib.parse import quote_plus

from app.services.naver_client import NaverClient, NaverProduct
from app.services.platform_resolver import AMAZON_US_SEARCH, build_search_query

_MAX_WORKERS = 8
_HANGUL = re.compile(r"[가-힣]")
# 네이버가 브랜드 미상일 때 채우는 대체값('네이버쇼핑'은 한글이라 한글 필터를 통과하므로 명시 제외).
_JUNK_BRANDS = {"네이버쇼핑", "네이버"}
_LATIN = re.compile(r"[A-Za-z]")


def _korean_brand(items: list[NaverProduct], fallback: str) -> str:
    """결과들의 brand 필드에서 첫 '한글 브랜드'를 고른다. 없으면 원문 브랜드를 유지한다.

    네이버는 브랜드 미상이면 '네이버쇼핑'·'UNKNOWN' 같은 값을 넣는다. 정크값을 제외하고
    한글 포함 브랜드만 채택(세라비/닥터자르트/라로슈포제 등). 한글 브랜드가 없으면 원문
    영문 브랜드(예: The Ordinary)를 그대로 둔다.
    """
    for item in items:
        brand = (item.brand or "").strip()
        if brand and brand not in _JUNK_BRANDS and _HANGUL.search(brand):
            return brand
    return fallback


def _preserve_original_amazon_link(product: object, brand: str, name: str) -> None:
    query = build_search_query(brand, name)
    if not _LATIN.search(query):
        return
    links = dict(getattr(product, "platform_links", None) or {})
    links["amazon_us"] = f"{AMAZON_US_SEARCH}{quote_plus(query)}"
    product.platform_links = links


def _enrich_one(product: object, client: NaverClient) -> bool:
    brand = str(getattr(product, "brand", "") or "")
    name = str(getattr(product, "name", "") or "")
    query = build_search_query(brand, name)
    items = client.search(query, hits=5)
    if not items:
        return False
    top = items[0]
    _preserve_original_amazon_link(product, brand, name)
    # 한글화: 이름/URL/이미지는 상위 결과, 브랜드는 결과 중 첫 유효 한글 브랜드.
    product.name = top.name
    product.brand = _korean_brand(items, brand)
    product.product_url = top.product_url
    product.source = "naver"
    if not str(getattr(product, "image_url", "") or "").strip() and top.image_url:
        product.image_url = top.image_url
    return True


def enrich_products_with_naver_kr(products: Iterable[object]) -> int:
    """KR 상품들을 네이버 한글 데이터로 제자리 보강한다. 반환값: 보강된 개수.

    products: brand/name/product_url/image_url/source 속성을 가진 (mutable) 객체 목록.
    """
    client = NaverClient()
    if not client.configured:
        return 0
    targets = [p for p in products if str(getattr(p, "name", "") or "").strip()]
    if not targets:
        return 0

    enriched = 0
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(targets))) as executor:
        futures = {executor.submit(_enrich_one, product, client): product for product in targets}
        for future in as_completed(futures):
            try:
                if future.result():
                    enriched += 1
            except Exception:
                pass
    return enriched
