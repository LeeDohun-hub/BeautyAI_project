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
from app.services.oliveyoung_catalog import catalog_available, match_oliveyoung
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
# 퍼스널컬러 톤/계절 수식어. 쇼핑 검색어에 섞이면(예: '클리오 소프트 쿨톤') 0건이 되므로 제거.
_TONE_WORDS = {
    "쿨톤", "웜톤", "쿨", "웜", "봄웜", "여름쿨", "가을웜", "겨울쿨", "뮤트", "브라이트",
    "cool", "warm", "cooltone", "warmtone", "mute", "muted", "bright",
}
_DROP_TAIL = _COLOR_WORDS | _STRUCT_WORDS | _TONE_WORDS

# 라쿠텐/마켓 리스팅 정제용. 상품명이 프로모·기프트·샵이름 범벅이라 그대로 검색하면 0건이 된다.
_BRACKET_SPAN = re.compile(r"【[^】]*】|\[[^\]]*\]|「[^」]*」|（[^）]*）|\([^)]*\)")
# 라쿠텐 프로모 배너는 전각 ＼…／ 로 감싸는 경우가 많다(예: '＼超トクで最大2000円OFF+全品Pアップ／').
# 구간을 통째로 제거한다(내부 문구가 매번 달라 개별 단어로는 다 못 잡는다).
_PROMO_SPAN = re.compile(r"＼[^／]*／")
_PROMO_WORDS = re.compile(
    # 주의: 농도 '30%'·'0.5%'는 상품 정체성이므로, %/円 은 OFF/オフ/還元 등 프로모 문맥에서만 제거.
    r"送料無料|ポイント\d+倍|ポイントアップ|Pアップ"
    r"|\d+円(?:\s*(?:OFF|オフ))?|\d+\s*[%％]\s*(?:OFF|オフ)|\d+\s*(?:OFF|オフ)|\d+%?還元"
    r"|超トク|お得|全品|正規取扱店?|正規品|公式|限定|海外通販|通販"
    r"|ギフト|プレゼント|人気|新品|新色|割引|クーポン|即日発送|最大|美容液|数量限定"
    r"|デパコス|アイメイク|メイクアップ|コスメ|オフ|セール",
    re.I,
)
_SHOP_SUFFIX = re.compile(r"(公式ショップ|楽天市場店|オンラインショップ|正規取り扱い店|公式|ショップ|本店|店)\s*$")
# '쇼핑'은 네이버가 브랜드 미상일 때 채우는 정크 브랜드('네이버쇼핑')를 잡기 위함.
# 이런 값이 검색 쿼리 앞에 붙으면(예: '네이버쇼핑 하우스랩스 페어') 올리브영이 0건을 반환한다.
_SHOP_HINT = re.compile(r"ショップ|楽天|store|shop|shopping|쇼핑|beauty|cosme|コスメ|通販|mall|市場|直営|flagship", re.I)
_NOISE = re.compile(r"(?:\d+(?:\.\d+)?\s*(?:ml|g|oz|호|색|colors?|個|枚))", re.I)
_JAPANESE_RE = re.compile(r"[ぁ-んァ-ン一-龥]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9%+.'-]*|\d+%")


def _drop_leading_jp_prefix_before_latin_brand(name: str) -> str:
    tokens = name.split()
    if len(tokens) < 2:
        return name
    first, second = tokens[0], tokens[1]
    latin_count = len(_LATIN_RE.findall(second))
    if _JAPANESE_RE.search(first) and not _LATIN_RE.search(first) and latin_count >= 3:
        return " ".join(tokens[1:])
    return name


def _clean_name(name: str) -> str:
    name = _PROMO_SPAN.sub(" ", name or "")          # ＼…／ 프로모 배너 통째 제거(브래킷보다 먼저)
    name = _BRACKET_SPAN.sub(" ", name)              # 【...】 등 괄호 안 내용까지 통째 제거
    name = name.split("|")[0]                        # '|' 이후 카테고리/기프트 태그 버림
    # ' - ' 또는 ' / ' 이후 쉐이드/사이즈/영문별칭 버림. 슬래시는 '공백에 인접'할 때만
    # 구분자로 본다. 'AHA/BHA'·'30ml/1oz'처럼 붙은 슬래시는 상품 정체성이라 자르면 안 된다
    # (예: 'AHA/BHA Clarifying Treatment Toner'를 자르면 'AHA'만 남아 검색이 0건이 됨).
    name = re.split(r"\s[-‐–—]\s|\s/|/\s", name)[0]
    name = _PROMO_WORDS.sub(" ", name)               # 프로모 키워드 제거
    name = _NOISE.sub(" ", name)                     # 용량/수량
    name = re.sub(r"[|｜/／]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return _drop_leading_jp_prefix_before_latin_brand(name)


def _clean_brand(brand: str) -> str:
    return _SHOP_SUFFIX.sub("", (brand or "").strip()).strip()


def _english_alias_query(name: str) -> str:
    candidates = re.split(r"[/／|｜]", name or "")
    if len(candidates) < 2:
        return ""
    for candidate in reversed(candidates):
        if not _LATIN_RE.search(candidate):
            continue
        candidate = _NOISE.sub(" ", candidate.replace(",", " "))
        tokens = [
            token.strip(" .'-")
            for token in _LATIN_TOKEN_RE.findall(candidate)
            if token.strip(" .'-").lower() not in {"ml", "g", "oz", "fl"}
        ]
        latin_words = [token for token in tokens if _LATIN_RE.search(token)]
        if len(latin_words) >= 3:
            return " ".join(tokens[:10])
    return ""


def _normalize_oy_brand(brand: str) -> str:
    """올리브영 검색용 브랜드 정규화. 'Dr. Jart+' → 'Dr.Jart+'처럼 점 뒤 공백을 없앤다.

    올리브영 검색은 구두점/공백에 민감해 'Dr. Jart'(공백)는 0건, 'Dr.Jart'는 매칭된다(실측).
    """
    return re.sub(r"\.\s+", ".", _clean_brand(brand)).strip()

RAKUTEN_SEARCH = "https://search.rakuten.co.jp/search/mall/"
NAVER_SEARCH = "https://search.shopping.naver.com/search/all?query="
AMAZON_JP_SEARCH = "https://www.amazon.co.jp/s?k="
AMAZON_US_SEARCH = "https://www.amazon.com/s?k="
# 올리브영: 한국 지역은 국내몰(oliveyoung.co.kr), 일본 지역은 글로벌몰(global.oliveyoung.com).
OLIVEYOUNG_KR_SEARCH = "https://www.oliveyoung.co.kr/store/search/getSearchMain.do?query="
OLIVEYOUNG_GLOBAL_SEARCH = "https://global.oliveyoung.com/display/search?query="
# JP 글로벌몰: 카탈로그 매칭 시 붙이는 '상품 직링크'(검색 아님 → 오탐 원천 차단).
OLIVEYOUNG_GLOBAL_DETAIL = "https://global.oliveyoung.com/product/detail?prdtNo="
# KR 국내몰의 goodsNo 직링크/입점 검증은 oliveyoung_kr_search(NewMainSearchApi + curl_cffi)가
# 담당한다. 글로벌 API의 gdsCd는 EAN 바코드라 국내몰 goodsNo가 아니다(실측).


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


def oliveyoung_query_candidates(brand: str, name: str) -> list[str]:
    """올리브영 검색 후보 쿼리(구체적→일반). 첫 매칭 후보를 버튼 URL에 쓴다.

    핵심: '브랜드 + 긴 영문 풀네임' 전체를 넘기면 실제 취급 상품도 0건이 된다(올리브영은
    사실상 AND/구문 매칭). 그래서 라인 코어 토큰을 1~2개로 줄이되, **모든 후보에 브랜드를
    유지**한다. 브랜드를 빼고 라인어만 쓰면 'Moisturizing Cream' 같은 일반명사가 엉뚱한
    상품에 매칭돼(오탐) 미취급 상품에도 버튼이 붙기 때문이다.
    """
    nb = _normalize_oy_brand(brand)
    core = build_search_query("", name).split()
    core_lc = " ".join(core).lower()
    # 브랜드를 앞에 붙일지: 정크/샵 브랜드('네이버쇼핑', '○○ショップ' 등)이거나 이미 상품명에
    # 포함돼 있으면 붙이지 않는다(예: 브랜드 '오휘' + 이름 '오휘 더퍼스트…' → '오휘 오휘…' 중복 방지).
    use_brand = bool(nb) and not _SHOP_HINT.search(nb) and "쇼핑" not in nb and nb.lower() not in core_lc
    cands: list[str] = []
    if use_brand and len(core) >= 2:
        cands.append(f"{nb} {core[0]} {core[1]}")
    if use_brand and core:
        cands.append(f"{nb} {core[0]}")
    if use_brand:
        cands.append(nb)
    if not use_brand:  # 브랜드를 못 쓰면 상품명 코어 토큰만으로 후보를 만든다.
        if len(core) >= 3:
            cands.append(" ".join(core[:3]))
        if len(core) >= 2:
            cands.append(" ".join(core[:2]))
        if core:
            cands.append(core[0])
    if not cands:  # 최후 방어: 기존 정제 쿼리라도 쓴다.
        cands.append(build_search_query(brand, name))
    seen: set[str] = set()
    out: list[str] = []
    for cand in cands:
        cand = cand.strip()
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


_HANGUL_RE = re.compile(r"[가-힣]")


def _korean_tokens(text: str) -> list[str]:
    return [token for token in (text or "").split() if _HANGUL_RE.search(token)]


def oliveyoung_kr_query(brand: str, name: str) -> str:
    """올리브영 국내몰(oliveyoung.co.kr)용 검색어 — 한글 토큰 우선.

    한국 플랫폼은 한글 검색이 안전하다(사용자 확인). 그런데 네이버로 보강한 수입 브랜드
    상품명은 '영문 … 한글 …'이 섞여 있고 한글이 뒤쪽에 오기도 한다(예: 'La Roche Posay
    Cicaplast … 라로슈포제 시카플라스트'). 그래서 상품명 전체에서 한글 토큰만 뽑아 앞쪽
    2~3개로 쿼리를 만든다. 한글이 전혀 없으면 기존 후보 쿼리(영문)로 폴백한다.
    """
    cleaned = _clean_name(name)
    ko = _korean_tokens(cleaned)
    # 꼬리의 쉐이드/구조/색상 한글 수식어 제거(라인명만 남긴다).
    while ko and ko[-1] in _DROP_TAIL:
        ko.pop()
    if not ko:
        return oliveyoung_query_candidates(brand, name)[0]
    core = ko[:3]
    nb = _normalize_oy_brand(brand)
    # 한글 브랜드가 상품명 앞에 없으면 붙인다(예: 브랜드 '세라비'가 이미 첫 토큰이면 생략).
    # 단 '네이버쇼핑' 같은 정크 브랜드(_SHOP_HINT)는 쿼리를 오염시키므로 붙이지 않는다.
    if nb and _HANGUL_RE.search(nb) and not _SHOP_HINT.search(nb) and nb != core[0] and nb not in core:
        core = [nb] + core
    return " ".join(core[:3]).strip()


def _oliveyoung_global_link(brand: str, name: str) -> str:
    """올리브영 글로벌몰 링크. 카탈로그가 있으면 매칭 상품의 prdtNo 직링크(없으면 빈 문자열),
    카탈로그 전(크롤 전)이면 라이브 검색 링크로 폴백한다(routes의 prune_global이 검증/제거)."""
    if catalog_available():
        match = match_oliveyoung(brand, name)
        return OLIVEYOUNG_GLOBAL_DETAIL + quote_plus(match.prdt_no) if match else ""
    cand = oliveyoung_query_candidates(brand, name)[0]
    return OLIVEYOUNG_GLOBAL_SEARCH + quote_plus(cand)


def _oliveyoung_kr_link(brand: str, name: str) -> str:
    """올리브영 국내몰 잠정 링크(한글 검색). 실제 입점 검증과 goodsNo 직링크 교체/제거는
    oliveyoung_kr_search.prune_kr_oliveyoung 이 런타임 라이브 검색으로 담당한다."""
    return OLIVEYOUNG_KR_SEARCH + quote_plus(oliveyoung_kr_query(brand, name))


def _is_kbeauty_brand(brand: str) -> bool:
    b = (brand or "").lower()
    return any(name in b for name in KBEAUTY_BRANDS)


def _is_jbeauty_brand(brand: str) -> bool:
    b = (brand or "").lower()
    return any(name in b for name in JBEAUTY_BRANDS)


def _search_url(base: str, brand: str, name: str, suffix: str = "") -> str:
    return f"{base}{quote_plus(build_search_query(brand, name))}{suffix}"


def _sync_platform_buttons(product, links: dict[str, str]) -> None:
    cleaned = {platform: url for platform, url in links.items() if url}
    product.platform_links = cleaned
    product.matched_platforms = sorted(cleaned.keys())


def resolve_product_platforms(product, region: str, *, hide_oliveyoung: bool = False) -> None:
    """상품 하나의 platform_links / matched_platforms를 권위있게 재구성한다(제자리 수정).

    카탈로그 상품이 갖고 있던 '풀네임 검색링크'(올리브영 0건 유발)를 버리고,
    검증된 실 URL(라쿠텐/네이버 소스, 마츠키요 인덱스) + 라인명 검색링크로 다시 만든다.

    hide_oliveyoung=True면 올리브영 버튼을 붙이지 않는다. KR 국내몰은 자동 검증이 불가라
    글로벌몰 조회 결과를 입점 대리 신호로 써서(oliveyoung_availability) 0건이면 숨긴다.
    """
    brand, name = product.brand or "", product.name or ""
    source = getattr(product, "source", "") or ""
    existing_links = dict(getattr(product, "platform_links", None) or {})
    direct_rakuten_url = product.product_url if source == "rakuten" and product.product_url else existing_links.get("rakuten", "")
    has_direct_rakuten = bool(direct_rakuten_url)
    direct_naver_url = product.product_url if source == "naver" and product.product_url else existing_links.get("naver", "")
    has_direct_naver = bool(direct_naver_url)
    links: dict[str, str] = {}

    if region == "jp":
        # 라쿠텐: 라쿠텐 소스면 실 상품 URL, 아니면 라인명 검색 링크(카탈로그 상품도 라쿠텐 버튼).
        if has_direct_rakuten:
            links["rakuten"] = direct_rakuten_url
        else:
            links["rakuten"] = _search_url(RAKUTEN_SEARCH, brand, name, suffix="/")
        # 마츠키요: 드롭(banned.md 참고 — 색조 크롤 데이터 없음 + 안티봇으로 검증 불가).
        # 아마존 JP: 라인명 검색 링크.
        if not has_direct_rakuten:
            links["amazon_jp"] = _search_url(AMAZON_JP_SEARCH, brand, name)
        # 올리브영: 일본 지역은 글로벌몰. 글로벌몰은 K뷰티+글로벌 브랜드(The Ordinary 등)를
        # 취급하므로, 일본 드럭스토어(J-뷰티) 브랜드만 제외하고 붙인다.
        if not _is_jbeauty_brand(brand):
            if catalog_available():
                # 카탈로그 매칭은 prdtNo '직링크'(검증됨)라 오탐 위험이 없다. 따라서 라쿠텐
                # 실상품(has_direct_rakuten)에도 붙인다 — 라쿠텐에서 찾은 K뷰티 상품이 올리브영
                # 글로벌에도 있으면 두 버튼을 함께 노출해야 하기 때문(예전엔 라쿠텐 상품이면
                # 올리브영 매칭 자체를 건너뛰어 'JP에 아예 안 붙는' 문제가 있었다).
                match = match_oliveyoung(brand, name)
                if match:
                    links["oliveyoung"] = OLIVEYOUNG_GLOBAL_DETAIL + quote_plus(match.prdt_no)
            elif not has_direct_rakuten:
                # 카탈로그가 없을 때만 잠정 '검색 링크'로 걸고, 실입점 검증/정제는
                # prune_global_oliveyoung 이 담당한다(0건이면 제거). 검색 링크는 미검증이므로
                # 라쿠텐 직링크 상품엔 붙이지 않는다(투기적 버튼 방지).
                oy = _oliveyoung_global_link(brand, name)
                if oy:
                    links["oliveyoung"] = oy
    else:  # KR
        if has_direct_naver:
            links["naver"] = direct_naver_url
        else:
            links["naver"] = _search_url(NAVER_SEARCH, brand, name)
        english_alias = _english_alias_query(name) if has_direct_naver else ""
        if english_alias:
            links["amazon_us"] = f"{AMAZON_US_SEARCH}{quote_plus(english_alias)}"
        elif has_direct_naver and existing_links.get("amazon_us"):
            links["amazon_us"] = existing_links["amazon_us"]
        elif not has_direct_naver:
            links["amazon_us"] = _search_url(AMAZON_US_SEARCH, brand, name)
        # 국내몰(oliveyoung.co.kr)은 Cloudflare 403으로 직접 검증이 불가하다. 대신 글로벌몰
        # 조회를 KR 입점 대리 신호로 써서(routes에서 보강 전 영문 정체성으로 판정) 조회되는
        # 상품만 '한글 우선 쿼리' 검색 링크로 노출한다(한국 플랫폼은 한글 검색이 안전).
        if not hide_oliveyoung:
            oy = _oliveyoung_kr_link(brand, name)
            if oy:
                links["oliveyoung"] = oy

    _sync_platform_buttons(product, links)


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
