"""상품 대표 이미지 실시간 보강.

DB/카탈로그 상품은 이미지가 없거나 죽은 URL(예: 올리브영 CDN 403)을 가진 경우가 많다.
Amazon 이미지 **API**는 유료·자격심사라 못 쓰지만, 우리가 이미 갖고 있는 아마존 Beauty
**카탈로그(CSV)의 imageUrl** 과 라쿠텐 검색 결과로 대체 이미지를 끌어온다.

여러 소스를 우선순위대로 **캐스케이드**해, 하나가 비거나 죽으면 다음 소스로 넘어간다:
- 한국(KR): 올리브영 국내몰 카탈로그 → 올리브영 글로벌 카탈로그 → 아마존 Beauty 카탈로그.
- 일본(JP): 라쿠텐 이치바(`mediumImageUrls`) → 올리브영 글로벌 카탈로그 → 아마존 JP 카탈로그.

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
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings
from app.services.amazon_catalog import match_for_region, product_form, sized_image_url
from app.services.oliveyoung_catalog import match_oliveyoung
from app.services.oliveyoung_kr_search import match_kr_catalog
# ⚠ 모듈 최상단에서 임포트한다(순환 없음 — platform_resolver 는 이 모듈을 임포트하지 않는다).
# 함수 안 지연 임포트로 두면 `_resolve_image` 의 try/except 가 ImportError 까지 삼켜서
# **KR 이미지가 전부 조용히 빈값**이 된다(실측: 실패 원인이 로그에 안 남아 커버리지 0 으로 보였다).
from app.services.platform_resolver import matching_brand
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


def oliveyoung_kr_image(brand: str, name: str) -> str:
    """올리브영 **국내몰** 카탈로그(로컬 CSV)에서 매칭 상품의 대표 이미지를 찾는다.

    KR 카드에는 이게 1순위다: 한글 상품명끼리 매칭하고(글로벌 카탈로그는 영문명),
    이미지 보유 75.1%(4,757/6,332)에 생존 100%(표본 250) 였다. 매칭 자체는 KR 올리브영
    **버튼과 같은** `match_kr_catalog` 라 버튼이 여는 goodsNo 의 사진이 붙는다.
    """
    match = match_kr_catalog(brand, name)
    return match.image_url if match else ""


def oliveyoung_catalog_image(brand: str, name: str) -> str:
    """올리브영 글로벌 카탈로그(로컬 CSV)에서 브랜드+상품명 매칭 상품의 대표 이미지를 찾는다."""
    match = match_oliveyoung(brand, name)
    return match.image_url if match else ""


def _amazon_image(brand: str, name: str, region: str) -> str:
    """아마존 Beauty 카탈로그에서 대표 이미지를 가져온다(m.media-amazon.com).

    매칭은 아마존 **버튼과 같은** `match_for_region` 을 쓴다 — 버튼이 여는 ASIN 의 사진이라
    '검색 1위 추측'보다 정확하고, 버튼과 사진이 서로 다른 상품일 수 없다.

    아마존 CDN 은 (1)다른 도메인 Referer 로도 200/JPEG 를 주고(핫링크 차단 없음),
    (2)ASIN 이 폐기(404)된 상품의 이미지도 계속 서빙한다 — 실측 확인. 그래서 죽은 링크
    문제와 무관하게 이미지 소스로 쓸 수 있다.
    """
    match = match_for_region(matching_brand(brand, name), name, region)
    if not match or not match.image_url:
        return ""
    return sized_image_url(match.image_url)


def amazon_image(brand: str, name: str) -> str:
    return _amazon_image(brand, name, "kr")


def amazon_jp_image(brand: str, name: str) -> str:
    return _amazon_image(brand, name, "jp")


# 카탈로그 매처는 **풀네임**으로만 질의한다. `_resolve_image` 의 짧은 질의(용량·뒷부분을
# 떼어낸 것)는 검색 API 0건을 피하려는 장치인데, 카탈로그 매칭에 넣으면 라인 토큰이 줄어
# 커버리지 분모가 작아지고 **형제 상품**(같은 브랜드의 다른 라인)이 문턱을 넘는다 → 버튼과
# 다른 상품 사진이 붙는다. 카탈로그는 0건이 정상 결과이므로 재시도할 이유도 없다.
amazon_image.full_name_only = True  # type: ignore[attr-defined]
amazon_jp_image.full_name_only = True  # type: ignore[attr-defined]
oliveyoung_kr_image.full_name_only = True  # type: ignore[attr-defined]
oliveyoung_catalog_image.full_name_only = True  # type: ignore[attr-defined]


# 지역별 이미지 소스 우선순위. 앞에서부터 시도해 살아있는 첫 이미지를 채택한다.
#
# 올리브영 이미지 배제(2026-07-27) **해제됨**(2026-08-03, 사용자 결정). 배제의 전제였던
# '핫링크 차단 / 죽은 URL·403이 잦다' 가 실측으로 성립하지 않았다:
#   - Referer 없음 / 다른 도메인(cross-site) / 올영 자기 도메인 → 응답이 **완전히 동일**.
#     실제 Chrome 으로 다른 오리진에서 <img> 24/24 렌더(nosniff 헤더도 없음).
#   - 생존율: image.oliveyoung.co.kr 250/250, image.oliveyoung.com 244/250(97.6%).
# 남은 위험(죽은 URL 2.4%)은 `_is_live_image` 가 이미 걸러낸다 → 아마존과 달리 올영은
# 신뢰 호스트에 넣지 않고 매번 검증한다.
#
# ⚠ 네이버 쇼핑 검색 API 는 2026-07-31 종료됐다(HTTP 200 + total 0 으로 조용히 죽는다).
# 캐스케이드에서 뺀 이유는 '죽은 소스라 못 채우기 때문'만이 아니라, 상품당 최대 4회(질의 변형)
# 헛 HTTP 왕복을 만들어 item-match 지연을 그만큼 늘리기 때문이다. `naver_image` 함수 자체는
# 남겨둔다(회귀 테스트 + 네이버가 대체 API 로 돌아올 경우 재연결 지점).
_PROVIDER_CASCADE: dict[str, list[Callable[[str, str], str]]] = {
    "kr": [oliveyoung_kr_image, oliveyoung_catalog_image, amazon_image],
    "jp": [rakuten_image, oliveyoung_catalog_image, amazon_jp_image],
}

_IMAGE_MAGIC = (b"\xff\xd8", b"\x89PNG", b"GIF8", b"RIFF")

# 검증 없이 신뢰하는 이미지 CDN. 아마존 미디어 CDN 은 실측(무작위 120건, 4개 카탈로그) 전부
# 200/JPEG 였고, 다른 도메인 Referer 로도 열리며(핫링크 차단 없음), ASIN 이 폐기(404)된 상품의
# 이미지도 계속 서빙한다. 반면 검증은 카드당 왕복 ~0.27s 를 더하고, 8스레드 동시 검증에서는
# 3초 타임아웃에 걸려 **살아있는 이미지를 버리는** 오탐이 났다(실측 33건 중 3건).
# 만에 하나 죽어도 프론트 `ProductImage` 의 onError 가 placeholder 로 떨어뜨린다(=현재 상태).
_TRUSTED_IMAGE_HOSTS = frozenset({"m.media-amazon.com"})


def _is_live_image(url: str) -> bool:
    """URL이 실제 이미지를 반환하는지 확인한다(올리브영 403/XML 등 죽은 URL 걸러냄).

    HTTP 200 + 앞부분 매직바이트(JPEG/PNG/GIF/WEBP)로 판별한다. 올리브영 CDN은 유효
    이미지를 `application/octet-stream`으로도 주므로 content-type이 아니라 바이트로 본다.
    결과는 TTL 캐시로 재확인을 줄인다. `_TRUSTED_IMAGE_HOSTS` 는 확인 없이 통과시킨다.
    """
    url = (url or "").strip()
    if not url:
        return False
    if urlsplit(url).netloc.lower() in _TRUSTED_IMAGE_HOSTS:
        return True
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
) -> str | None:
    """현재 이미지가 살아있으면 유지(None 반환), 아니면 소스 캐스케이드로 살아있는 이미지를 찾는다.

    반환값: 새로 채택한 URL, 유지면 None, 전부 실패면 "" (placeholder로 비움).

    출처(호스트)로 걸러내지 않는다 — 판정 기준은 '살아있는가' 하나다. 예전엔 올리브영 URL 이면
    살아있어도 버렸는데(2026-07-27 배제), 그 결과 **정답 이미지를 버리고 검색으로 추측한 다른
    상품 이미지**가 붙었다(실측: medicube 바디로션·아누아 선크림 카드). 배제 전제(핫링크 차단·
    높은 사망률)는 2026-08-03 실측에서 성립하지 않아 해제했다(위 캐스케이드 주석 참고).
    """
    if current and _is_live_image(current):
        # 이미 아마존 이미지를 들고 있는 상품(DB 시드)은 크기 지시자만 카드 규격으로 통일한다.
        # 지시자 없는 원본은 1500px/190KB 짜리도 있어, 카드 10장이면 2MB 를 그냥 태운다.
        sized = sized_image_url(current)
        return None if sized == current else sized
    # 풀네임 → 짧은 질의 순으로 시도한다(긴 영문명은 대부분 0건).
    # 단, 카탈로그 매처(full_name_only)는 짧은 질의를 주면 형제 상품이 매칭되므로 풀네임만 준다.
    queries = [name, *(_short_queries(brand, name))]
    for provider in providers:
        for query in ([name] if getattr(provider, "full_name_only", False) else queries):
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
