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

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable
from urllib.parse import quote_plus

from app.services.naver_client import NaverClient, NaverProduct
from app.services.oliveyoung_catalog import match_oliveyoung
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


def _hangul_token_count(name: str) -> int:
    """상품명에 포함된 '한글이 든 단어' 수. 국내몰 매칭이 잘 되려면 한글 라인명이 많아야 한다."""
    return sum(1 for token in html.unescape(name or "").split() if _HANGUL.search(token))


def _choose_result(items: list[NaverProduct]) -> NaverProduct:
    """상위 결과 중 '한글 토큰이 가장 많은' 결과를 고른다(동률은 sim 상위 유지).

    네이버 sim 1위가 해외셀러 영문 타이틀('CLIO PRO EYE PALETTE AIR 08 …')인 경우가 잦은데,
    같은 라인의 한글 타이틀('클리오 프로 아이 팔레트 에어 …')이 하위에 있으면 그쪽이 국내몰
    매칭에 훨씬 유리하다. 모두 영문/코드면 그대로 1위를 쓴다(악화 없음).
    """
    best = items[0]
    best_kr = _hangul_token_count(items[0].name)
    for item in items[1:]:
        kr = _hangul_token_count(item.name)
        if kr > best_kr:
            best, best_kr = item, kr
    return best


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
    top = _choose_result(items)
    _preserve_original_amazon_link(product, brand, name)
    # 한글화: 이름/URL/이미지는 '한글 최다' 결과, 브랜드는 결과 중 첫 유효 한글 브랜드.
    # HTML 엔티티('rom&amp;nd')를 디코드해 국내몰 검색/표시가 깨지지 않게 한다.
    product.name = html.unescape(top.name or "")
    product.brand = _korean_brand(items, brand)
    product.product_url = top.product_url
    product.source = "naver"
    if not str(getattr(product, "image_url", "") or "").strip() and top.image_url:
        product.image_url = top.image_url
    return True


def _enrich_one_from_catalog(product: object) -> bool:
    """올리브영 글로벌 카탈로그의 한글 상품명으로 한글화한다(네트워크 없음).

    카탈로그 행에 영문명(name_en)과 한글명(name_kr)이 함께 있어서, 영문 상품명으로 매칭만
    되면 한글명을 바로 얻는다. 네이버 쇼핑 검색(2026-07-31 종료)이 하던 일을 로컬 데이터로
    대신하는 것이다.

    **이름과 브랜드만 바꾼다.** 네이버 경로는 URL·이미지까지 덮어썼지만 여기서는 손대지 않는다.
      - 링크는 뒤따르는 resolve_product_platforms 가 지역별로 붙인다(여기서 글로벌몰 URL을
        박으면 KR 카드가 글로벌몰로 가버린다).
      - 올리브영 이미지는 미리보기에서 배제하기로 한 정책이 있다(product_image_provider).
    """
    brand = str(getattr(product, "brand", "") or "")
    name = str(getattr(product, "name", "") or "")
    if not name:
        return False
    # 이미 한글이면 건드릴 이유가 없다(국내몰 검색이 그대로 먹는다).
    if _HANGUL.search(name):
        return False

    match = match_oliveyoung(brand, name)
    if match is None:
        return False
    name_kr = (match.name_kr or "").strip()
    if not name_kr or not _HANGUL.search(name_kr):
        return False

    _preserve_original_amazon_link(product, brand, name)
    product.name = html.unescape(name_kr)
    # 한글명 첫 토큰이 곧 한글 브랜드다('라운드랩 자작나무 …'). 한글이 아니면 원문 유지.
    head = name_kr.split()[0]
    if _HANGUL.search(head):
        product.brand = head
    return True


def enrich_products_with_naver_kr(products: Iterable[object]) -> int:
    """KR 상품들을 한글 데이터로 제자리 보강한다. 반환값: 보강된 개수.

    products: brand/name/product_url/image_url/source 속성을 가진 (mutable) 객체 목록.

    2단 폴백이다.
      1. **로컬 카탈로그**(올리브영 글로벌 `korPrdtName`) — 네트워크 0, 오탐 0. 항상 먼저 쓴다.
      2. 네이버 쇼핑 검색 — 자격증명이 있을 때만. 2026-07-31 종료되어 사실상 죽은 경로지만,
         키가 살아 있는 환경(사설 프록시 등)에서 동작하도록 남겨둔다.

    ⚠️ 종료된 쇼핑 API 는 **200 OK + 빈 결과**를 준다. 예외가 안 나서 조용히 0건이 되므로,
    1번이 먼저 돌지 않으면 한글화가 통째로 사라진 걸 아무도 모른다(실측: 배포 후에야 발견).
    """
    targets = [p for p in products if str(getattr(p, "name", "") or "").strip()]
    if not targets:
        return 0

    enriched = 0
    remaining: list[object] = []
    for product in targets:
        try:
            if _enrich_one_from_catalog(product):
                enriched += 1
            else:
                remaining.append(product)
        except Exception:  # noqa: BLE001 - 보강 실패가 추천을 깨지 않게 한다.
            remaining.append(product)

    client = NaverClient()
    if not client.configured or not remaining:
        return enriched

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(remaining))) as executor:
        futures = {executor.submit(_enrich_one, product, client): product for product in remaining}
        for future in as_completed(futures):
            try:
                if future.result():
                    enriched += 1
            except Exception:
                pass
    return enriched
