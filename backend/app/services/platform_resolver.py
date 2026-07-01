"""상품 입점 리졸버 (product-centric availability resolver).

상품 1개(브랜드+상품명)에 대해 "어디서 살 수 있나"를 플랫폼 버튼으로 채운다.
소스별 카드가 아니라 상품별 카드가 되도록 각 상품에 플랫폼 링크를 붙인다.

링크 종류:
- 실 상품 URL(검증): 라쿠텐/네이버 소스 상품의 원 URL, 마츠키요 로컬 인덱스 매칭.
- 검색 링크(퍼지): 그 외 플랫폼은 '브랜드+라인명' 검색 링크. 라쿠텐/아마존/올리브영 검색은
  퍼지라 라인명으로 검색하면 해당 상품이 나온다(사용자 확인).

검색어는 build_search_query로 상품명 꼬리의 쉐이드/색상 수식어를 떼어 만든다.
"Coral Series" 같은 쉐이드가 붙으면 올리브영 등 strict 검색이 0건을 반환하기 때문.
(퍼스널컬러는 '발견/랭킹/카드 문구'에서 이미 반영되므로 딥링크는 라인 페이지로 간다.)

라이브 API 매칭을 상품마다 돌리면 레이트리밋/지연이 커서, 검색 링크로 대체한다.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from app.services.matsukiyo_matcher import normalize_key
from app.services.recommender import JBEAUTY_BRANDS, KBEAUTY_BRANDS

# 상품명 '꼬리'에 붙는 쉐이드(색상)·구조(시리즈/에디션) 수식어. 라인명만 남길 때 제거.
_COLOR_WORDS = {
    "coral", "pink", "peach", "beige", "red", "brown", "rose", "nude", "mauve", "plum",
    "berry", "wine", "burgundy", "cherry", "apricot", "camel", "mocha", "brick",
    "terracotta", "ivory", "champagne", "olive", "khaki", "lavender", "navy",
    "charcoal", "sand", "gray", "grey", "silver", "black", "orange", "yellow",
    "코랄", "핑크", "피치", "베이지", "레드", "브라운", "로즈", "누드", "모브", "플럼",
    "베리", "와인", "버건디", "체리", "살구", "카멜", "모카", "브릭", "아이보리",
    "샴페인", "올리브", "카키", "라벤더", "네이비", "차콜", "샌드", "그레이", "실버",
    "블랙", "오렌지", "옐로우",
}
_STRUCT_WORDS = {
    "series", "collection", "edition", "set", "shade", "limited", "mini", "vol", "no",
    "kit", "pack", "시리즈", "컬렉션", "에디션", "세트", "한정", "미니", "호", "색",
    "컬러", "키트", "팩",
}
_DROP_TAIL = _COLOR_WORDS | _STRUCT_WORDS

# 라쿠텐/마켓 리스팅 정제용. 상품명이 프로모·기프트·샵이름 범벅이라 그대로 검색하면 0건이 된다.
_BRACKET_SPAN = re.compile(r"【[^】]*】|\[[^\]]*\]|「[^」]*」|（[^）]*）|\([^)]*\)")
_PROMO_WORDS = re.compile(
    r"送料無料|ポイント\d+倍|\d+%?還元|正規取扱店?|正規品|公式|限定|海外通販|通販"
    r"|ギフト|プレゼント|人気|新品|新色|割引|クーポン|即日発送|最大|美容液|数量限定"
    r"|デパコス|アイメイク|メイクアップ|コスメ|オフ|セール",
    re.I,
)
_SHOP_SUFFIX = re.compile(r"(公式ショップ|楽天市場店|オンラインショップ|正規取り扱い店|公式|ショップ|本店|店)\s*$")
_SHOP_HINT = re.compile(r"ショップ|楽天|store|shop|beauty|cosme|コスメ|通販|mall|市場|直営|flagship", re.I)
_NOISE = re.compile(r"(?:\d+(?:\.\d+)?\s*(?:ml|g|oz|호|색|colors?|個|枚))", re.I)


def _clean_name(name: str) -> str:
    name = _BRACKET_SPAN.sub(" ", name or "")       # 【...】 등 괄호 안 내용까지 통째 제거
    name = name.split("|")[0]                        # '|' 이후 카테고리/기프트 태그 버림
    name = re.split(r"\s[-‐–—]\s|/", name)[0]        # ' - ' 또는 '/' 이후 쉐이드/사이즈/옵션 버림
    name = _PROMO_WORDS.sub(" ", name)               # 프로모 키워드 제거
    name = _NOISE.sub(" ", name)                     # 용량/수량
    name = re.sub(r"[|｜/／]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _clean_brand(brand: str) -> str:
    return _SHOP_SUFFIX.sub("", (brand or "").strip()).strip()

RAKUTEN_SEARCH = "https://search.rakuten.co.jp/search/mall/"
NAVER_SEARCH = "https://search.shopping.naver.com/search/all?query="
AMAZON_JP_SEARCH = "https://www.amazon.co.jp/s?k="
AMAZON_US_SEARCH = "https://www.amazon.com/s?k="
# 올리브영: 한국 지역은 국내몰(oliveyoung.co.kr), 일본 지역은 글로벌몰(global.oliveyoung.com).
OLIVEYOUNG_KR_SEARCH = "https://www.oliveyoung.co.kr/store/search/getSearchMain.do?query="
OLIVEYOUNG_GLOBAL_SEARCH = "https://global.oliveyoung.com/display/search?query="


def build_search_query(brand: str, name: str) -> str:
    """프로모/샵이름/쉐이드 노이즈를 걷어내고 '브랜드 + 핵심 라인명'만 남긴다.

    라쿠텐 리스팅명(예: '【ポイント10倍】...ボビイ ブラウン ヌード アイシャドウ | ギフト...')을
    그대로 검색하면 아마존/마츠키요에서 0건이 나오므로, 검색이 실제로 걸리도록 정제한다.
    """
    cleaned = _clean_name(name)
    tokens = cleaned.split()
    # 꼬리의 쉐이드/구조/숫자 수식어 제거 후 길이 제한(과도한 토큰은 strict 검색 0건 유발).
    while tokens and (tokens[-1].lower() in _DROP_TAIL or tokens[-1].isdigit()):
        tokens.pop()
    core = " ".join(tokens[:6]) if tokens else cleaned

    brand_clean = _clean_brand(brand)
    # 브랜드가 실제 브랜드일 때만 앞에 붙인다. 샵이름(Strawberrynet, ○○ショップ 등)이거나
    # 이미 상품명에 포함되어 있으면 붙이지 않는다(쿼리 오염 방지).
    if brand_clean and not _SHOP_HINT.search(brand_clean) and brand_clean.lower() not in core.lower():
        return f"{brand_clean} {core}".strip()
    return core


def _is_kbeauty_brand(brand: str) -> bool:
    b = (brand or "").lower()
    return any(name in b for name in KBEAUTY_BRANDS)


def _is_jbeauty_brand(brand: str) -> bool:
    b = (brand or "").lower()
    return any(name in b for name in JBEAUTY_BRANDS)


def _search_url(base: str, brand: str, name: str, suffix: str = "") -> str:
    return f"{base}{quote_plus(build_search_query(brand, name))}{suffix}"


def resolve_product_platforms(product, region: str) -> None:
    """상품 하나의 platform_links / matched_platforms를 권위있게 재구성한다(제자리 수정).

    카탈로그 상품이 갖고 있던 '풀네임 검색링크'(올리브영 0건 유발)를 버리고,
    검증된 실 URL(라쿠텐/네이버 소스, 마츠키요 인덱스) + 라인명 검색링크로 다시 만든다.
    """
    brand, name = product.brand or "", product.name or ""
    source = getattr(product, "source", "") or ""
    links: dict[str, str] = {}

    if region == "jp":
        # 라쿠텐: 라쿠텐 소스면 실 상품 URL, 아니면 라인명 검색 링크(카탈로그 상품도 라쿠텐 버튼).
        if source == "rakuten" and product.product_url:
            links["rakuten"] = product.product_url
        else:
            links["rakuten"] = _search_url(RAKUTEN_SEARCH, brand, name, suffix="/")
        # 마츠키요: 드롭(banned.md 참고 — 색조 크롤 데이터 없음 + 안티봇으로 검증 불가).
        # 아마존 JP: 라인명 검색 링크.
        links["amazon_jp"] = _search_url(AMAZON_JP_SEARCH, brand, name)
        # 올리브영: 일본 지역은 글로벌몰. 글로벌몰은 K뷰티+글로벌 브랜드(The Ordinary 등)를
        # 취급하므로, 일본 드럭스토어(J-뷰티) 브랜드만 제외하고 붙인다.
        if not _is_jbeauty_brand(brand):
            links["oliveyoung"] = _search_url(OLIVEYOUNG_GLOBAL_SEARCH, brand, name)
    else:  # KR
        if source == "naver" and product.product_url:
            links["naver"] = product.product_url
        else:
            links["naver"] = _search_url(NAVER_SEARCH, brand, name)
        links["amazon_us"] = _search_url(AMAZON_US_SEARCH, brand, name)
        links["oliveyoung"] = _search_url(OLIVEYOUNG_KR_SEARCH, brand, name)

    product.platform_links = links
    product.matched_platforms = sorted(links.keys())


def _line_key(product) -> tuple[str, str]:
    return (normalize_key(product.brand or ""), normalize_key(build_search_query("", product.name or "")))


def dedup_by_line(products: list) -> list:
    """같은 상품(브랜드+라인명)의 중복 카드를 병합한다. 링크/이미지가 많은 쪽을 남긴다."""
    merged: dict[tuple[str, str], object] = {}
    order: list[tuple[str, str]] = []
    for product in products:
        key = _line_key(product)
        if key not in merged:
            merged[key] = product
            order.append(key)
            continue
        keep = merged[key]
        combined = dict(keep.platform_links or {})
        for platform, url in (product.platform_links or {}).items():
            combined.setdefault(platform, url)
        keep.platform_links = combined
        keep.matched_platforms = sorted(combined.keys())
        if not keep.image_url and product.image_url:
            keep.image_url = product.image_url
        if (product.score or 0) > (keep.score or 0):
            keep.score = product.score
    return [merged[key] for key in order]
