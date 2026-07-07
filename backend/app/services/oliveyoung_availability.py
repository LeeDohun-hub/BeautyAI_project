"""올리브영 글로벌몰(global.oliveyoung.com) 실시간 입점 확인 — JP 지역 폴백용.

로컬 카탈로그(oliveyoung_catalog)가 있으면 JP는 카탈로그 직링크로 판정하므로 이 라이브
검증은 카탈로그가 없을 때만 쓰인다. 판정: 검색 결과가 있으면 브랜드 필터 사이드바가 렌더돼
HTML에 'brandCheck' 마커가 다수 등장한다(빈 결과 페이지엔 없음). 이 마커로 결과 유무를 본다.

국내몰(oliveyoung.co.kr)은 별도 모듈(oliveyoung_kr_search)이 curl_cffi로 담당한다.

정책:
- 브랜드를 포함한 후보 쿼리를 구체적→일반 순으로 시도해, 결과가 있는 첫 쿼리를 채택한다.
- 브랜드명만 남는 느슨한 fallback은 쓰지 않는다(브랜드 검색 결과가 상품 입점 근거는 아니므로).
- 모든 후보가 0건이거나 네트워크 오류로 확인 불가하면 올리브영 버튼을 숨긴다.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable
from urllib.parse import quote_plus

import httpx

from app.services.platform_resolver import (
    OLIVEYOUNG_GLOBAL_SEARCH,
    oliveyoung_query_candidates,
)

_REQUEST_TIMEOUT = 6.0
_CACHE_TTL_SECONDS = 60 * 60  # 1시간 — 입점 여부는 자주 바뀌지 않는다.
_MAX_WORKERS = 8
_RESULTS_HTML_BYTES = 300_000  # 빈 결과 페이지 ≈279KB. 이보다 크면 결과가 있다는 보조 신호.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

_MISS = object()
_cache: dict[str, tuple[float, bool | None]] = {}  # key: 검색 쿼리
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


def _has_results(query: str) -> bool | None:
    """글로벌몰 검색 결과 유무. True=있음, False=0건, None=확인 불가(네트워크 오류 등)."""
    query = (query or "").strip()
    if not query:
        return None
    cached = _cache_get(query)
    if cached is not _MISS:
        return cached
    try:
        response = httpx.get(
            OLIVEYOUNG_GLOBAL_SEARCH + quote_plus(query),
            headers={"user-agent": _USER_AGENT, "accept-language": "en-US,en;q=0.9"},
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        body = response.text
    except Exception:
        _cache_set(query, None)
        return None
    result = ("brandCheck" in body) or (len(body) > _RESULTS_HTML_BYTES)
    _cache_set(query, result)
    return result


def resolve_global_query(brand: str, name: str) -> str | None:
    """검증된 글로벌몰 검색어를 반환한다. 없으면 None(버튼 숨김).

    엄격 정책: 확인 불가(네트워크 오류)도 None으로 처리해 버튼을 숨긴다.
    """
    candidates = oliveyoung_query_candidates(brand, name)
    if len(candidates) > 1:
        # 마지막 후보는 대개 브랜드 단독 쿼리다. 상품 존재 여부로 보기엔 너무 느슨하다.
        candidates = candidates[:-1]
    for query in candidates:
        result = _has_results(query)
        if result is True:
            return query
    return None  # 전부 0건/확인 불가 → 숨김


def prune_global_oliveyoung(products: Iterable[object]) -> None:
    """상품들의 oliveyoung(글로벌) 링크를 검증해 갱신/제거한다(제자리 수정).

    - 결과가 있으면: 링크를 '검증된 최적 후보' 검색 URL로 교체한다.
    - 전부 0건이면: platform_links / matched_platforms 에서 oliveyoung 을 제거한다.
    """
    items = [
        product
        for product in products
        if "oliveyoung" in (getattr(product, "platform_links", None) or {})
    ]
    if not items:
        return
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(items))) as executor:
        futures = {
            executor.submit(resolve_global_query, product.brand or "", product.name or ""): product
            for product in items
        }
        for future in as_completed(futures):
            product = futures[future]
            try:
                best = future.result()
            except Exception:
                best = None
            links = dict(product.platform_links or {})
            if best:
                links["oliveyoung"] = OLIVEYOUNG_GLOBAL_SEARCH + quote_plus(best)
            else:
                links.pop("oliveyoung", None)
            product.platform_links = links
            product.matched_platforms = sorted(links.keys())


def clear_cache() -> None:
    """테스트용 캐시 초기화."""
    with _cache_lock:
        _cache.clear()
