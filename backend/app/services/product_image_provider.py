"""상품 대표 이미지 실시간 보강.

DB/카탈로그 상품은 이미지가 없거나 죽은 URL(예: 올리브영 CDN 403)을 가진 경우가 많다.
Amazon 이미지 API가 막혀 있어, 이미 연결된 실시간 검색 API/카탈로그로 대체 이미지를 끌어온다.

여러 소스를 우선순위대로 **캐스케이드**해, 하나가 비거나 죽으면 다음 소스로 넘어간다:
- 한국(KR): 네이버 쇼핑(`image`) → 올리브영 글로벌 카탈로그(`imageUrl`).
- 일본(JP): 라쿠텐 이치바(`mediumImageUrls`) → 올리브영 글로벌 카탈로그 → 네이버.

브랜드가 어긋난 엉뚱한 이미지가 붙지 않도록, 브랜드를 아는 경우 브랜드 토큰이
겹치는 결과만 채택한다. 후보 URL은 실제로 이미지가 응답하는지 검증(`_is_live_image`)해서
채택하므로, 죽은 URL은 살아있는 다른 소스 이미지로 교체된다. 모든 소스가 실패할 때만
빈 문자열로 두어(프론트 placeholder) 마지막 폴백을 한다. 결과는 TTL 캐시로 재검색을 줄인다.
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable

import httpx

from app.core.config import get_settings
from app.services.amazon_catalog import product_form
from app.services.oliveyoung_catalog import match_oliveyoung
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


def _form_conflicts(want: str, candidate_title: str) -> bool:
    """상품명이 뜻하는 제형과 후보 리스팅의 제형이 다르면 True(엉뚱한 이미지 차단).

    아마존 매처의 제형 판정을 재사용한다 — 같은 브랜드의 다른 제품(선크림 vs 수딩크림,
    바디로션 vs 토너패드)이 검색 상위에 오면 이미지가 통째로 다른 상품이 된다
    (실측: 'Anua Heartleaf Silky Moisture Sun Cream' 카드에 선크림 아닌 이미지,
    'medicube Red Clear Capsule Body Lotion' 카드에 다른 메디큐브 상품 이미지).
    """
    if not want:
        return False
    got = product_form(candidate_title or "")
    return bool(got) and got != want


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
    want_form = product_form(name)
    # 브랜드만으로 검색했을 때(상품 토큰이 없음)는 '1위 결과' 폴백을 쓰지 않는다.
    # 그 폴백이 이미지 불일치의 직접 원인이었다: _resolve_image 가 긴 상품명으로 0건이면
    # 마지막에 브랜드만 남긴 질의로 재검색하는데, 거기서 1위 이미지를 채택하면 같은 브랜드의
    # **아무 상품** 이미지가 카드에 붙는다(실측: medicube 바디로션 카드에 다른 메디큐브 상품).
    brand_only = not (name_tokens - brand_tokens)
    fallback = ""
    chosen = ""
    for item in items:
        image = str(item.get("image") or "").strip()
        if not image:
            continue
        title = str(item.get("title") or "")
        if _form_conflicts(want_form, title):
            continue  # 제형이 다른 상품(선크림 자리에 토너 등) → 이미지로 쓰지 않는다
        item_tokens = _tokens(f"{title} {item.get('brand', '')} {item.get('maker', '')}")
        # 브랜드/상품명 토큰이 겹치면 확실한 일치 → 즉시 채택.
        # 국내 브랜드는 네이버에 한글명(예: rom&nd→롬앤)으로 올라와 영문 토큰이
        # 안 겹칠 수 있으므로, 겹치는 게 없으면 유사도 1위 결과 이미지를 대안으로 쓴다.
        # (검색어 자체가 "브랜드+상품명"이라 1위 결과 신뢰도가 높다.)
        if (brand_tokens & item_tokens) or (name_tokens & item_tokens):
            chosen = image
            break
        if not fallback and not brand_only:
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
    want_form = product_form(name)
    if client.configured:
        for product in client.search(query, hits=3):
            # 제형이 다른 리스팅(라쿠텐은 같은 브랜드의 다른 제품·부속품이 상위에 잘 온다)은 건너뛴다.
            if product.image_url and not _form_conflicts(want_form, product.name or ""):
                result = product.image_url
                break
    _cache_set(key, result)
    return result


def oliveyoung_catalog_image(brand: str, name: str) -> str:
    """올리브영 글로벌 카탈로그(로컬 CSV)에서 브랜드+상품명 매칭 상품의 대표 이미지를 찾는다."""
    match = match_oliveyoung(brand, name)
    return match.image_url if match else ""


# 지역별 이미지 소스 우선순위. 앞에서부터 시도해 살아있는 첫 이미지를 채택한다.
# 올리브영 이미지는 미리보기에 쓰지 않는다(사용자 지시 2026-07-27): CDN 죽은 URL·403이 잦고
# 상품카드 미리보기 신뢰도가 낮아, KR=네이버·JP=라쿠텐 이미지로만 채운다(없으면 placeholder).
_PROVIDER_CASCADE: dict[str, list[Callable[[str, str], str]]] = {
    "kr": [naver_image],
    "jp": [rakuten_image, naver_image],
}


def _is_oliveyoung_image(url: str) -> bool:
    """올리브영 이미지 CDN URL인지(미리보기에서 배제 대상)."""
    return "oliveyoung" in (url or "").lower()


def _has_oliveyoung_direct_link(item: object) -> bool:
    """카드의 올리브영 버튼이 '상품 직링크'인지(검색 링크가 아닌 prdtNo/goodsNo 상세페이지).

    직링크면 그 상품이 특정되므로 카탈로그 이미지를 신뢰할 수 있다. 검색 링크는 어떤 상품이
    열릴지 모르니 종전대로 지역 소스 이미지로 교체한다.
    """
    url = ((getattr(item, "platform_links", None) or {}).get("oliveyoung") or "").lower()
    return bool(url) and ("product/detail" in url or "getgoodsdetail" in url)

_IMAGE_MAGIC = (b"\xff\xd8", b"\x89PNG", b"GIF8", b"RIFF")


def _is_live_image(url: str) -> bool:
    """URL이 실제 이미지를 반환하는지 확인한다(올리브영 403/XML 등 죽은 URL 걸러냄).

    HTTP 200 + 앞부분 매직바이트(JPEG/PNG/GIF/WEBP)로 판별한다. 올리브영 CDN은 유효
    이미지를 `application/octet-stream`으로도 주므로 content-type이 아니라 바이트로 본다.
    결과는 TTL 캐시로 재확인을 줄인다.
    """
    url = (url or "").strip()
    if not url:
        return False
    key = f"live::{url}"
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached == "1"

    ok = False
    try:
        with httpx.stream(
            "GET",
            url,
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as response:
            if response.status_code == 200:
                head = next(response.iter_bytes(chunk_size=8), b"")
                ok = head.startswith(_IMAGE_MAGIC)
    except Exception:
        ok = False

    _cache_set(key, "1" if ok else "0")
    return ok


# 용량·수량·구성 토큰. 검색어에서 빼야 실제 상품이 잡힌다("...Cleanser 120ml" → 0건).
_SIZE_TOKEN_RE = re.compile(r"^\d+(\.\d+)?(ml|g|kg|oz|매|개|개입|종|팩|세트|ea|p|매입)?$|^\d+$", re.I)
_NOISE_TOKEN_RE = re.compile(r"^(set|pack|count|refill|본품|기획|단품|증정|리필)$", re.I)


def _short_queries(brand: str, name: str) -> list[str]:
    """검색어 후보를 '구체적 → 일반' 순으로 만든다.

    카탈로그 상품명은 'Isntree Yam Root Vegan pH-balancing Cleanser 120ml' 처럼 길어서,
    그대로 넣으면 네이버/라쿠텐이 사실상 AND 매칭이라 0건이 나온다(실측: 4개 중 3개 실패).
    용량·수량을 떼고 앞쪽 핵심어만 남긴 짧은 질의로 재시도한다.
    """
    tokens = [
        token for token in re.split(r"[\s/,()\[\]]+", (name or "").strip())
        if token and not _SIZE_TOKEN_RE.match(token) and not _NOISE_TOKEN_RE.match(token)
    ]
    brand = (brand or "").strip()
    # 상품명이 브랜드로 시작하면 중복되지 않게 뗀다.
    if brand and tokens and tokens[0].lower() == brand.lower().split()[0]:
        tokens = tokens[1:]
    out: list[str] = []
    for take in (4, 3, 2):
        if len(tokens) >= take:
            candidate = " ".join(([brand] if brand else []) + tokens[:take]).strip()
            if candidate and candidate not in out:
                out.append(candidate)
    if brand and brand not in out:
        out.append(brand)
    return out


def _resolve_image(
    brand: str,
    name: str,
    current: str,
    providers: list[Callable[[str, str], str]],
    oy_direct: bool = False,
) -> str | None:
    """현재 이미지가 살아있으면 유지(None 반환), 아니면 소스 캐스케이드로 살아있는 이미지를 찾는다.

    반환값: 새로 채택한 URL, 유지면 None, 전부 실패면 "" (placeholder로 비움).

    oy_direct=True(카드의 구매 버튼이 올리브영 **상품 직링크**)면 올리브영 카탈로그 이미지를
    유지한다. 올영 이미지 배제 지시(2026-07-27)는 '죽은 URL·403이 잦다'는 이유였고 그 판정은
    _is_live_image 가 이미 하는데, 배제만 남으니 **정답 이미지를 버리고 검색으로 추측한 다른
    상품 이미지**가 붙었다(실측: medicube 바디로션·아누아 선크림 카드). 직링크가 가리키는
    상품의 카탈로그 이미지는 정의상 그 상품이라 추측보다 정확하다.
    """
    if current and _is_live_image(current) and (oy_direct or not _is_oliveyoung_image(current)):
        return None
    # 풀네임 → 짧은 질의 순으로 시도한다(긴 영문명은 대부분 0건).
    queries = [name, *(_short_queries(brand, name))]
    for provider in providers:
        for query in queries:
            if not query:
                continue
            try:
                candidate = str(provider(brand, query) or "").strip()
            except Exception:
                candidate = ""
            if candidate and candidate != current and _is_live_image(candidate):
                return candidate
    return ""


def fill_missing_images(items: Iterable[object], region: str) -> int:
    """상품 객체의 image_url을 지역별 소스 캐스케이드로 채우거나 교체한다(제자리 수정).

    이미지가 없는 상품은 물론, 죽은 URL(예: 올리브영 403)을 가진 상품도 검증해서 살아있는
    다른 소스 이미지로 교체한다. 모든 소스가 실패하면 빈 문자열로 비운다(프론트 placeholder).

    items: image_url/brand/name 속성을 가진 (mutable) 객체 목록.
    반환값: 실제로 이미지를 채우거나 교체한 개수.
    """
    providers = _PROVIDER_CASCADE.get((region or "").strip().lower())
    if not providers:
        return 0

    targets = [item for item in items if str(getattr(item, "name", "") or "").strip()]
    if not targets:
        return 0

    filled = 0
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(targets))) as executor:
        futures = {
            executor.submit(
                _resolve_image,
                str(getattr(item, "brand", "") or ""),
                str(getattr(item, "name", "") or ""),
                str(getattr(item, "image_url", "") or "").strip(),
                providers,
                _has_oliveyoung_direct_link(item),
            ): item
            for item in targets
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                resolved = future.result()
            except Exception:
                resolved = None
            if resolved is not None and resolved != str(getattr(item, "image_url", "") or "").strip():
                item.image_url = resolved
                if resolved:
                    filled += 1
    return filled


def clear_cache() -> None:
    """테스트용 캐시 초기화."""
    with _cache_lock:
        _cache.clear()
