"""올리브영 국내몰(oliveyoung.co.kr) 실시간 검색 — Cloudflare 우회 + goodsNo 직링크.

국내몰은 Cloudflare가 requests/httpx의 비-브라우저 TLS 지문을 403으로 막는다. curl_cffi 의
`impersonate="chrome"` 는 진짜 Chrome TLS/JA3 지문을 흉내내 수동 쿠키 없이 통과한다(실측).

내부 검색 API `NewMainSearchApi.do` 가 JSON을 준다:
- Parameter[0].totalCount : 결과 수(0이면 미취급 확정 → 버튼 숨김)
- Data[0].Result[]        : GOODS_NO(국내몰 goodsNo), GOODS_NM, ONL_BRND_NM, GOODS_SOUT_INFO

검색 상위 결과가 항상 정답은 아니라('오휘 더퍼스트' 검색의 1등이 '오휘 포맨'), 결과마다
브랜드/상품명을 line_match_score 로 채점해 맞는 상품만 goodsNo 직링크로 노출한다(오탐 차단).
"""

from __future__ import annotations

import csv
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus

try:  # curl_cffi 미설치 환경에서도 앱이 죽지 않게(검증 불가 → 버튼 유지로 폴백).
    from curl_cffi import requests as _creq
except Exception:  # pragma: no cover
    _creq = None

from app.core.config import get_settings
from app.services.matsukiyo_matcher import normalize_key, tokens_for
from app.services.oliveyoung_catalog import line_match_score, score_line
from app.services.platform_resolver import build_search_query, oliveyoung_kr_query

_KR_CATALOG_FILENAME = "oliveyoung_kr_products.csv"

_SEARCH_API = "https://www.oliveyoung.co.kr/store/search/NewMainSearchApi.do"
_GOODS_DETAIL = "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo="
_SEARCH_REFERER = "https://www.oliveyoung.co.kr/store/search/getSearchMain.do"
_REQUEST_TIMEOUT = 8.0
_CACHE_TTL_SECONDS = 60 * 60  # 1시간 — 입점/재고는 자주 안 바뀐다.
_MAX_WORKERS = 6
_MATCH_MIN_SCORE = 0.5

_MISS = object()
_cache: dict[str, object] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class KRResult:
    goods_no: str
    brand: str
    name: str
    sold_out: bool


@dataclass(frozen=True)
class KRSearch:
    total_count: int
    results: tuple[KRResult, ...]


def kr_goods_url(goods_no: str) -> str:
    return _GOODS_DETAIL + quote_plus(goods_no)


# ── 로컬 KR 카탈로그(배치 크롤 산출물) ──────────────────────────────────────────
# scripts/crawl_oliveyoung_kr.py 가 만든 CSV. 런타임은 이걸 먼저 매칭하고(즉시), 없을 때만
# 라이브 검색으로 폴백해 국내몰 호출을 줄인다. 없으면 항상 라이브(그레이스풀).

@dataclass(frozen=True)
class _KRItem:
    result: KRResult
    brand_key: str
    brand_tokens: frozenset[str]
    name_tokens: frozenset[str]


def _kr_catalog_path() -> Path:
    return get_settings().project_root / "data" / "manifests" / _KR_CATALOG_FILENAME


@lru_cache(maxsize=1)
def _load_kr_catalog() -> tuple[_KRItem, ...]:
    path = _kr_catalog_path()
    if not path.exists():
        return ()
    items: list[_KRItem] = []
    with path.open(encoding="utf-8-sig", errors="ignore", newline="") as f:
        for row in csv.DictReader(f):
            goods_no = str(row.get("goodsNo") or "").strip()
            name = str(row.get("goodsName") or "").strip()
            if not goods_no or not name:
                continue
            brand = str(row.get("brandName") or "").strip()
            items.append(
                _KRItem(
                    result=KRResult(
                        goods_no=goods_no,
                        brand=brand,
                        name=name,
                        sold_out=str(row.get("soldOut") or "").strip().upper() == "Y",
                    ),
                    brand_key=normalize_key(brand),
                    brand_tokens=tokens_for(brand),
                    name_tokens=tokens_for(name),
                )
            )
    return tuple(items)


def clear_kr_catalog_cache() -> None:
    _load_kr_catalog.cache_clear()


def kr_catalog_available() -> bool:
    return bool(_load_kr_catalog())


def match_kr_catalog(brand: str, name: str, min_score: float = _MATCH_MIN_SCORE) -> KRResult | None:
    """로컬 KR 카탈로그에서 최적 매칭(재고 있는 상품)을 찾는다. 없으면 None."""
    q_brand_key = normalize_key(brand)
    q_brand_tokens = tokens_for(brand)
    q_name_tokens = tokens_for(name)
    if not q_name_tokens:
        return None
    best: KRResult | None = None
    best_score = min_score
    for item in _load_kr_catalog():
        if item.result.sold_out:
            continue
        score = score_line(
            q_brand_key, q_brand_tokens, q_name_tokens,
            item.brand_key, item.brand_tokens, item.name_tokens,
        )
        if score is None or score < best_score:
            continue
        best, best_score = item.result, score
    return best


def _cache_get(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return _MISS
        ts, value = entry  # type: ignore[misc]
        if time.time() - ts > _CACHE_TTL_SECONDS:
            _cache.pop(key, None)
            return _MISS
        return value


def _cache_set(key: str, value) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
    clear_kr_catalog_cache()


def _parse(payload: dict) -> KRSearch:
    params = (payload.get("Parameter") or [{}])[0]
    total = int(params.get("totalCount") or 0)
    data = payload.get("Data") or []
    raw = (data[0].get("Result") or []) if data else []
    results = []
    for r in raw:
        goods_no = str(r.get("GOODS_NO") or "").strip()
        if not goods_no:
            continue
        results.append(
            KRResult(
                goods_no=goods_no,
                brand=str(r.get("ONL_BRND_NM") or r.get("ONL_BRND_NM_EN") or "").strip(),
                name=str(r.get("GOODS_NM") or "").strip(),
                sold_out=str(r.get("GOODS_SOUT_INFO") or "").strip().upper() == "Y",
            )
        )
    return KRSearch(total_count=total, results=tuple(results))


def search_kr(query: str) -> KRSearch | None:
    """국내몰 검색 결과. None=검증 불가(네트워크 오류/미설치). 캐시됨."""
    query = (query or "").strip()
    if not query or _creq is None:
        return None
    cached = _cache_get(query)
    if cached is not _MISS:
        return cached  # type: ignore[return-value]
    try:
        response = _creq.get(
            f"{_SEARCH_API}?query={quote_plus(query)}&pageIdx=1&rowsPerPage=24",
            impersonate="chrome",
            headers={"x-requested-with": "XMLHttpRequest", "referer": _SEARCH_REFERER},
            timeout=_REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        result = _parse(response.json())
    except Exception:
        return None
    _cache_set(query, result)
    return result


def _query_candidates(brand: str, name: str) -> list[str]:
    cands = [oliveyoung_kr_query(brand, name), build_search_query(brand, name)]
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        c = (c or "").strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


_HANGUL_RE = re.compile(r"[가-힣]")

# 영문 브랜드 → 한글 브랜드 별칭. 네이버가 한글 타이틀을 안 줘서 한글명에서 브랜드를 못 뽑는
# 경우(rom&nd 'B15026 Rom&nd …')에도 한글 브랜드로 국내몰 검색/채점이 되게 한다.
_BRAND_ALIAS = {
    "romnd": "롬앤", "romand": "롬앤", "peripera": "페리페라", "espoir": "에스쁘아",
    "clio": "클리오", "colorgram": "컬러그램", "cologram": "컬러그램", "wakemake": "웨이크메이크",
    "tirtir": "티르티르", "hera": "헤라", "laneige": "라네즈", "innisfree": "이니스프리",
    "etude": "에뛰드", "amuse": "어뮤즈", "muzigae": "무지개", "lilybyred": "릴리바이레드",
    "dasique": "데이지크", "fwee": "퓌", "clove": "클로브", "unleashia": "언리시아",
    "romandbyromnd": "롬앤", "holika": "홀리카", "missha": "미샤", "mediheal": "메디힐",
    "cosrx": "코스알엑스", "roundlab": "라운드랩", "torriden": "토리든", "numbuzin": "넘버즈인",
    "abib": "아비브", "anua": "아누아", "beautyofjoseon": "조선미녀", "skin1004": "스킨천사",
}


def _brand_alias_key(brand: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (brand or "").lower())


def _kr_brand(brand: str, name: str) -> str:
    """국내몰은 한글이라, 영문 DB 브랜드(peripera/CLIO)면 한글 브랜드를 쓴다.
    우선순위: (1) 이미 한글이면 그대로, (2) 알려진 영문→한글 별칭, (3) 한글명 첫 한글 토큰.
    이렇게 안 하면 line_match_score의 브랜드 매칭이 영문vs한글로 실패해 정상 상품도 기각된다."""
    if _HANGUL_RE.search(brand or ""):
        return brand
    alias = _BRAND_ALIAS.get(_brand_alias_key(brand))
    if alias:
        return alias
    for token in (name or "").split():
        if _HANGUL_RE.search(token):
            return token
    return brand


def _line_overlap(q_brand: str, q_name: str, c_brand: str, c_name: str) -> int:
    """브랜드 토큰을 제외한 '라인 토큰' 교집합 수. 형제라인(1토큰만 겹침) 오탐 차단용."""
    exclude = tokens_for(q_brand) | tokens_for(c_brand)
    ql = tokens_for(q_name) - exclude
    il = tokens_for(c_name) - exclude
    return len(ql & il)


def _kr_line_score(kr_brand: str, raw_name: str, clean_query: str, r: "KRResult") -> float | None:
    """국내몰 후보 채점: 원본명(노이즈 많음)과 정제쿼리 둘 다로 채점해 max를 쓴다.
    네이버 보강명은 프로모/영문/'매장상품' 등 잡토큰이 많아 Jaccard가 희석되므로 정제쿼리로도
    재본다. 단 라인토큰이 **2개 이상** 겹치는 쿼리만 인정한다(브랜드+1토큰만 겹치는 형제라인
    오탐 방지: '잉크무드'↔'잉크더벨벳'은 '잉크' 1개만 겹쳐 기각)."""
    best: float | None = None
    for q_name in (raw_name, clean_query):
        score = line_match_score(kr_brand, q_name, r.brand, r.name)
        if score is None:
            continue
        if _line_overlap(kr_brand, q_name, r.brand, r.name) < 2:
            continue
        if best is None or score > best:
            best = score
    return best


def resolve_kr_goods(brand: str, name: str) -> tuple[KRResult | None, bool]:
    """국내몰에서 이 상품에 맞는 goodsNo를 찾는다.

    반환 (match, verifiable):
    - match  : 채점 통과한 재고 있는 상품(있으면 goodsNo 직링크). 없으면 None.
    - verifiable : 검색 응답을 한 번이라도 받았으면 True(0건/무매칭 = 미취급 확정으로 숨김 가능).
                   전부 네트워크 오류면 False(확정 못 하므로 기존 버튼 유지).

    로컬 KR 카탈로그(배치 크롤)에 매칭이 있으면 라이브 호출 없이 그 결과를 쓴다. 카탈로그는
    브랜드별 상위 상품만 담아(top~20/쿼리) 불완전하므로, 미매칭은 '없음'이 아니라 라이브 폴백이다.
    """
    # 영문 DB 브랜드면 한글명에서 브랜드를 뽑아 국내몰(한글) 매칭이 되게 한다.
    kr_brand = _kr_brand(brand, name)
    cataloged = match_kr_catalog(kr_brand, name)
    if cataloged is not None:
        return cataloged, True

    clean_query = oliveyoung_kr_query(kr_brand, name)
    # 형제라인 오탐(잉크무드↔잉크더벨벳)은 _kr_line_score의 '라인토큰 2개 이상 겹침' 게이트가
    # 막으므로, 문턱은 기본 0.5를 쓴다(0.5357짜리 정상 매칭도 통과).
    live_min = _MATCH_MIN_SCORE
    got_response = False
    for query in _query_candidates(kr_brand, name):
        sr = search_kr(query)
        if sr is None:
            continue
        got_response = True
        if sr.total_count == 0:
            continue
        best: KRResult | None = None
        best_score = live_min
        for r in sr.results:
            if r.sold_out:
                continue
            score = _kr_line_score(kr_brand, name, clean_query, r)
            if score is None or score < best_score:
                continue
            best, best_score = r, score
        if best is not None:
            return best, True
    return None, got_response


def prune_kr_oliveyoung(products: Iterable[object]) -> None:
    """국내몰 실시간 검색으로 olive young 버튼을 goodsNo 직링크로 교체/제거한다(제자리 수정).

    - 매칭됨   : oliveyoung 링크를 goodsNo 상세 URL(직링크)로 교체.
    - 그 외    : oliveyoung 버튼 제거. 0건(미취급 확정)뿐 아니라 네트워크 오류/429(검증 불가)도
                 제거한다 — 잠정 검색 링크를 남기면 '올리브영에 실제로는 없는데 버튼이 붙는'
                 오탐이 생기기 때문(사용자 지적). 확실히 매칭된 상품(카탈로그/라이브)만 노출한다.
                 인기 상품은 로컬 KR 카탈로그(배치 크롤) 직링크로 429와 무관하게 계속 노출된다.
    """
    items = [
        p for p in products
        if "oliveyoung" in (getattr(p, "platform_links", None) or {})
    ]
    if not items:
        return
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(items))) as executor:
        futures = {
            executor.submit(resolve_kr_goods, getattr(p, "brand", "") or "", getattr(p, "name", "") or ""): p
            for p in items
        }
        for future in as_completed(futures):
            product = futures[future]
            try:
                match, _verifiable = future.result()
            except Exception:
                match = None
            links = dict(product.platform_links or {})
            if match is not None:
                links["oliveyoung"] = kr_goods_url(match.goods_no)
            else:
                links.pop("oliveyoung", None)
            product.platform_links = links
            product.matched_platforms = sorted(links.keys())
