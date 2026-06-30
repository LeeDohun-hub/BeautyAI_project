"""실시간 플랫폼 입점 확인.

추천 상품이 각 쇼핑몰에 실제로 존재하는지 확인해, 없는 곳의 버튼을 숨기기 위한
모듈이다. 현재 신뢰할 수 있는 공개 검색 수단이 있는 플랫폼은 **네이버**뿐이라
네이버만 실제 확인하고, 그 외 플랫폼은 확인 수단이 없어 "확인 불가(None)"로 둔다.

정책: 확인 결과가 명시적으로 "없음(False)"인 플랫폼만 숨기고,
"있음(True)"·"확인 불가(None)"는 모두 노출한다. (사용자 결정: 확인 불가 → 일단 표시)

네이버 자격증명(NAVER_CLIENT_ID/SECRET)이 없으면 네이버도 확인 불가로 처리되어
기존과 동일하게 모두 노출된다. 키를 .env 에 넣으면 자동으로 실제 확인이 켜진다.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

import httpx

from app.core.config import get_settings

NAVER_SHOP_API = "https://openapi.naver.com/v1/search/shop.json"
_REQUEST_TIMEOUT = 2.5
_CACHE_TTL_SECONDS = 60 * 60  # 1시간 — 입점 여부는 자주 바뀌지 않는다.
_MAX_WORKERS = 8

# 네이버 쇼핑은 한글 상품명 위주라 영문 '상품 풀네임' 검색은 실존 상품도 0건이 흔하다.
# 따라서 상품 단위 0건은 '없음'의 신뢰 신호가 아니다. 반면 '브랜드' 자체가 0건이면
# 그 브랜드는 네이버에 사실상 미입점으로 볼 수 있어, 이 경우에만 네이버를 숨긴다.

_MISS = object()
_cache: dict[str, tuple[float, bool | None]] = {}  # key: 정규화된 브랜드명
_cache_lock = threading.Lock()


def _cache_get(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return _MISS
        ts, value = entry
        if time.time() - ts > _CACHE_TTL_SECONDS:
            _cache.pop(key, None)
            return _MISS
        return value


def _cache_set(key: str, value: bool | None) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _naver_search_total(query: str) -> int | None:
    """네이버 쇼핑 검색 결과 건수. 자격증명/네트워크 문제 시 None(확인 불가)."""
    settings = get_settings()
    client_id = getattr(settings, "naver_client_id", None)
    client_secret = getattr(settings, "naver_client_secret", None)
    if not client_id or not client_secret:
        return None
    query = (query or "").strip()
    if not query:
        return None
    try:
        response = httpx.get(
            NAVER_SHOP_API,
            params={"query": query, "display": 1},
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None
    try:
        return int(data.get("total", 0))
    except (TypeError, ValueError):
        return None


def naver_available(brand: str, name: str = "") -> bool | None:
    """네이버 입점 여부(브랜드 기준, 캐시 적용).

    True=확인(브랜드 검색됨), False=미입점(브랜드 0건), None=확인 불가(키 없음/오류).
    name 인자는 인터페이스 호환을 위해 받지만 판정에는 브랜드만 사용한다.
    """
    key = (brand or "").strip().lower()
    if not key:
        return None
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    total = _naver_search_total(brand)
    result: bool | None = None if total is None else total > 0
    _cache_set(key, result)
    return result


def unavailable_platforms_bulk(
    products: Iterable[tuple[int, str, str, set[str]]],
) -> dict[int, set[str]]:
    """상품별로 '숨겨야 할' 플랫폼 집합을 반환한다.

    products: (product_id, brand, name, candidate_platforms) 반복 가능 객체.
    네이버 후보가 있는 상품만 병렬로 확인하고, 명시적으로 없음(False)인 경우만 숨긴다.
    """
    items = [item for item in products if "naver" in item[3]]
    if not items:
        return {}

    settings = get_settings()
    if not (getattr(settings, "naver_client_id", None) and getattr(settings, "naver_client_secret", None)):
        # 자격증명 없으면 네이버도 확인 불가 → 숨길 것 없음.
        return {}

    hidden: dict[int, set[str]] = {}
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(items))) as executor:
        futures = {
            executor.submit(naver_available, brand, name): product_id
            for product_id, brand, name, _candidates in items
        }
        for future in as_completed(futures):
            product_id = futures[future]
            try:
                available = future.result()
            except Exception:
                available = None
            if available is False:
                hidden.setdefault(product_id, set()).add("naver")
    return hidden


def clear_cache() -> None:
    """테스트용 캐시 초기화."""
    with _cache_lock:
        _cache.clear()
