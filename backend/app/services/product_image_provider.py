"""상품 대표 이미지 실시간 보강.

DB/카탈로그 상품은 이미지가 없는 경우가 많다. Amazon 이미지 API가 막혀 있어,
이미 연결된 실시간 검색 API로 대체 이미지를 끌어온다.

- 한국(KR) 상품: 네이버 쇼핑 검색의 첫 일치 상품 썸네일(`image`).
- 일본(JP) 상품: 라쿠텐 이치바 검색의 첫 상품 이미지(`mediumImageUrls`).

브랜드가 어긋난 엉뚱한 이미지가 붙지 않도록, 브랜드를 아는 경우 브랜드 토큰이
겹치는 결과만 채택한다. 키가 없거나 오류면 빈 문자열을 반환해 기존 placeholder를
유지한다. 결과는 TTL 캐시로 재검색을 줄인다.
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable

import httpx

from app.core.config import get_settings
from app.services.rakuten_client import RakutenClient

NAVER_SHOP_API = "https://openapi.naver.com/v1/search/shop.json"
_REQUEST_TIMEOUT = 3.0
_CACHE_TTL_SECONDS = 60 * 60 * 6  # 6시간 — 상품 대표 이미지는 자주 바뀌지 않는다.
_MAX_WORKERS = 8
_TAG_RE = re.compile(r"<[^>]+>")

_MISS = object()
_cache: dict[str, tuple[float, str]] = {}
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


def _cache_set(key: str, value: str) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _normalize(text: str) -> str:
    text = _TAG_RE.sub(" ", (text or "").lower())
    text = re.sub(r"[^0-9a-z가-힣ぁ-んァ-ン一-龥]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    return {token for token in _normalize(text).split() if len(token) >= 2}


def naver_image(brand: str, name: str) -> str:
    """네이버 쇼핑에서 브랜드+상품명으로 첫 일치 상품 썸네일 URL을 찾는다."""
    settings = get_settings()
    client_id = getattr(settings, "naver_client_id", None)
    client_secret = getattr(settings, "naver_client_secret", None)
    query = " ".join(part for part in (brand, name) if part).strip()
    if not (client_id and client_secret and query):
        return ""

    key = f"naver::{_normalize(query)}"
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached

    try:
        response = httpx.get(
            NAVER_SHOP_API,
            params={"query": query, "display": 5, "sort": "sim"},
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        items = response.json().get("items") or []
    except Exception:
        items = []

    brand_tokens = _tokens(brand)
    name_tokens = _tokens(name)
    fallback = ""
    chosen = ""
    for item in items:
        image = str(item.get("image") or "").strip()
        if not image:
            continue
        item_tokens = _tokens(
            f"{item.get('title', '')} {item.get('brand', '')} {item.get('maker', '')}"
        )
        # 브랜드/상품명 토큰이 겹치면 확실한 일치 → 즉시 채택.
        # 국내 브랜드는 네이버에 한글명(예: rom&nd→롬앤)으로 올라와 영문 토큰이
        # 안 겹칠 수 있으므로, 겹치는 게 없으면 유사도 1위 결과 이미지를 대안으로 쓴다.
        # (검색어 자체가 "브랜드+상품명"이라 1위 결과 신뢰도가 높다.)
        if (brand_tokens & item_tokens) or (name_tokens & item_tokens):
            chosen = image
            break
        if not fallback:
            fallback = image

    result = chosen or fallback
    _cache_set(key, result)
    return result


def rakuten_image(brand: str, name: str) -> str:
    """라쿠텐 이치바에서 브랜드+상품명으로 첫 상품 이미지 URL을 찾는다."""
    query = " ".join(part for part in (brand, name) if part).strip()
    if not query:
        return ""

    key = f"rakuten::{_normalize(query)}"
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached

    client = RakutenClient()
    result = ""
    if client.configured:
        for product in client.search(query, hits=3):
            if product.image_url:
                result = product.image_url
                break
    _cache_set(key, result)
    return result


def _provider_for(region: str) -> Callable[[str, str], str] | None:
    region = (region or "").strip().lower()
    if region == "kr":
        return naver_image
    if region == "jp":
        return rakuten_image
    return None


def fill_missing_images(items: Iterable[object], region: str) -> int:
    """이미지가 없는 상품 객체의 image_url을 지역별 API로 채운다(제자리 수정).

    items: image_url/brand/name 속성을 가진 (mutable) 객체 목록.
    반환값: 실제로 이미지를 채운 개수.
    """
    provider = _provider_for(region)
    if provider is None:
        return 0

    targets = [
        item
        for item in items
        if not str(getattr(item, "image_url", "") or "").strip()
        and str(getattr(item, "name", "") or "").strip()
    ]
    if not targets:
        return 0

    filled = 0
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(targets))) as executor:
        futures = {
            executor.submit(
                provider,
                str(getattr(item, "brand", "") or ""),
                str(getattr(item, "name", "") or ""),
            ): item
            for item in targets
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                image = future.result()
            except Exception:
                image = ""
            if image:
                item.image_url = image
                filled += 1
    return filled


def clear_cache() -> None:
    """테스트용 캐시 초기화."""
    with _cache_lock:
        _cache.clear()
