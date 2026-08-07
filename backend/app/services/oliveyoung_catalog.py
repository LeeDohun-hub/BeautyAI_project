"""올리브영 로컬 카탈로그 매처 (product → 입점/직링크).

라이브 검색으로 입점을 추측하던 방식(oliveyoung_availability)을 대체한다. 오프라인 크롤러
(scripts/crawl_oliveyoung_global.py)가 만든 CSV를 인메모리로 올려두고, 상품(브랜드+상품명)을
카탈로그와 조인한다. 매칭되면 prdtNo(글로벌)·gdsCd(국내몰 goodsNo 후보) 직링크를 만들 수 있고,
안 되면 '미취급'으로 확정할 수 있다 — 라이브 검색이 못 주던 '0건 판별'과 '오탐 방지'를 동시에.

매칭 로직/토큰 유틸은 matsukiyo_matcher 패턴을 재사용한다. CSV가 아직 없으면(크롤 전) 빈
카탈로그로 동작해, 호출부는 기존 검색 링크 폴백으로 자연스럽게 되돌아간다(catalog_available).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.services.matsukiyo_matcher import normalize_key, tokens_for

# 크롤러 산출물. FIELDNAMES는 scripts/crawl_oliveyoung_global.py 와 일치.
_CATALOG_FILENAME = "oliveyoung_global_products.csv"

# 제품종류(폼) family. 같은 브랜드/라인이라도 폼이 다르면(선크림 vs 토너) 다른 상품이다.
# 양쪽 상품명의 폼 family가 있고 서로 겹치지 않으면 매칭을 기각한다(오탐 방지).
#
# ⚠️ 영문↔한글을 같은 family로 묶는 게 핵심이다. DB 상품명은 영문("Cream"), 국내몰 라이브
# 검색 결과는 한글("크림")이라, family로 정규화하지 않으면 'cream vs 크림'이 서로 다른 폼으로
# 취급돼 정상 매칭까지 전부 기각된다(국내몰 KR 버튼 소실 회귀, 2026-07-08). 각 그룹은 동일
# 제품종류의 EN/KR 표기를 함께 담는다. tokens_for가 소문자+분절하므로 토큰도 소문자여야 한다.
_FORM_FAMILY_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"sunscreen", "sunblock", "sun", "sunstick", "선크림", "선블록", "선스틱"}),
    frozenset({"toner", "softener", "토너"}),
    frozenset({"cream", "크림"}),
    frozenset({"lotion", "로션"}),
    frozenset({"emulsion", "에멀전"}),
    frozenset({"serum", "세럼"}),
    frozenset({"essence", "에센스"}),
    frozenset({"ampoule", "앰플"}),
    frozenset({"cleanser", "cleansing", "wash", "클렌저", "클렌징"}),
    frozenset({"foam", "폼"}),
    frozenset({"gel", "젤"}),
    frozenset({"peeling", "필링"}),
    frozenset({"pack", "팩"}),
    frozenset({"mask", "마스크"}),
    frozenset({"patch", "패치"}),
    frozenset({"cushion", "쿠션"}),
    frozenset({"scrub", "스크럽"}),
    frozenset({"oil", "오일"}),
    frozenset({"mist", "미스트"}),
    frozenset({"pad", "패드"}),
    frozenset({"balm", "밤"}),
    frozenset({"powder", "파우더"}),
    frozenset({"tint", "틴트"}),
    frozenset({"lipstick", "립스틱"}),
    frozenset({"gloss", "글로스"}),
    frozenset({"blusher", "blush", "블러셔"}),
    frozenset({"concealer", "컨실러"}),
    frozenset({"primer", "프라이머"}),
    frozenset({"eyeshadow", "shadow", "섀도우"}),
    frozenset({"eyeliner", "liner", "아이라이너"}),
    frozenset({"mascara", "마스카라"}),
    frozenset({"foundation", "파운데이션"}),
    frozenset({"highlighter", "하이라이터"}),
)

# 토큰 → family 인덱스. 폼 토큰이 아니면 매핑에 없다.
_FORM_TOKEN_TO_FAMILY: dict[str, int] = {
    token: idx for idx, group in enumerate(_FORM_FAMILY_GROUPS) for token in group
}


def _form_families(tokens) -> set[int]:
    """토큰 집합에서 제품종류 family 인덱스 집합을 뽑는다(EN/KR 표기는 같은 family로 합쳐짐)."""
    return {_FORM_TOKEN_TO_FAMILY[t] for t in tokens if t in _FORM_TOKEN_TO_FAMILY}

# 재고 0은 링크 대상에서 제외한다(죽은 링크 방지). 실측상 sellStatCode="10"이 판매중이고
# 품절 코드값은 표본에 없어(추측 시 유효 상품을 잘못 버릴 위험) stockQty를 판매 신호로 쓴다.
# stockQty가 비었/파싱 불가면 버리지 않는다(과잉 필터 방지).


@dataclass(frozen=True)
class OYMatch:
    brand: str
    name_en: str
    name_kr: str
    prdt_no: str
    gds_cd: str
    score: float
    image_url: str = ""


@dataclass(frozen=True)
class _OYItem:
    brand: str
    name_en: str
    name_kr: str
    prdt_no: str
    gds_cd: str
    brand_key: str
    brand_tokens: frozenset[str]
    name_tokens: frozenset[str]
    name_en_tokens: frozenset[str] = frozenset()
    name_kr_tokens: frozenset[str] = frozenset()
    image_url: str = ""
    sale_amt: str = ""  # 글로벌몰 판매가(USD 원문). JP 남성 소스에서 카드 가격으로 변환해 쓴다.
    name_jp: str = ""   # 일본어 상품명(JP 지역 카드용). 크롤이 curLang=jp로 받아 채운다.
    brand_jp: str = ""  # 일본어 브랜드명(JP 지역 카드용).


@dataclass(frozen=True)
class OYCatalogItem:
    """글로벌몰 카탈로그 상품(카드 소스). 지역별 표기를 호출부가 고른다."""
    brand: str          # 영문/기본 브랜드(매칭·폴백용)
    brand_jp: str       # 일본어 브랜드
    name_kr: str
    name_en: str
    name_jp: str
    prdt_no: str
    image_url: str
    price_usd: float

    def localized_name(self, region: str) -> str:
        if region == "jp":
            return self.name_jp or self.name_en or self.name_kr
        return self.name_kr or self.name_en

    def localized_brand(self, region: str) -> str:
        if region == "jp":
            return self.brand_jp or self.brand
        return self.brand


def _catalog_path() -> Path:
    return get_settings().project_root / "data" / "manifests" / _CATALOG_FILENAME


def _in_stock(stock_qty: str) -> bool:
    """재고 0이면 False(죽은 링크 방지). 빈/파싱 불가는 True(신호 없음 → 유지)."""
    raw = str(stock_qty or "").strip()
    if not raw:
        return True
    try:
        return int(float(raw)) != 0
    except ValueError:
        return True


@lru_cache(maxsize=1)
def _load_items() -> tuple[_OYItem, ...]:
    path = _catalog_path()
    if not path.exists():
        return ()

    items: list[_OYItem] = []
    with path.open(encoding="utf-8-sig", errors="ignore", newline="") as file:
        for row in csv.DictReader(file):
            prdt_no = str(row.get("prdtNo") or "").strip()
            name_en = str(row.get("prdtNameEn") or "").strip()
            name_kr = str(row.get("korPrdtName") or "").strip()
            if not prdt_no or not (name_en or name_kr):
                continue
            if not _in_stock(row.get("stockQty")):
                continue
            brand = str(row.get("brandName") or "").strip()
            # 상품명은 영문+한글을 한 토큰셋에 담아, 네이버 한글 보강 전(영문)·후(한글) 어느
            # 정체성으로 들어와도 매칭되게 한다. 브랜드 토큰은 따로 둬서 라인 유사도(overlap)
            # 계산에서 제외한다(브랜드가 overlap과 보너스에 이중계상돼 오탐 나는 것 방지).
            items.append(
                _OYItem(
                    brand=brand,
                    name_en=name_en,
                    name_kr=name_kr,
                    prdt_no=prdt_no,
                    gds_cd=str(row.get("gdsCd") or "").strip(),
                    brand_key=normalize_key(brand),
                    brand_tokens=tokens_for(brand),
                    name_tokens=tokens_for(name_en, name_kr),
                    name_en_tokens=tokens_for(name_en),
                    name_kr_tokens=tokens_for(name_kr),
                    image_url=str(row.get("imageUrl") or "").strip(),
                    sale_amt=str(row.get("saleAmt") or row.get("nrmlAmt") or "").strip(),
                    name_jp=str(row.get("jpPrdtName") or "").strip(),
                    brand_jp=str(row.get("jpBrandName") or "").strip(),
                )
            )
    return tuple(items)


def clear_cache() -> None:
    """테스트/재크롤 후 인메모리 인덱스 초기화."""
    _load_items.cache_clear()
    catalog_brand_keys.cache_clear()
    match_oliveyoung.cache_clear()


def catalog_available() -> bool:
    """카탈로그 CSV가 로드되어 최소 1개 항목이 있으면 True.

    False면 호출부는 라이브 검색 링크(기존 동작)로 폴백해야 한다(크롤 전 그레이스풀).
    """
    return bool(_load_items())


@lru_cache(maxsize=1)
def catalog_brand_keys() -> frozenset[str]:
    """카탈로그가 취급하는 브랜드 키 집합(약 194개).

    `match_oliveyoung`은 후보 3천여 개를 전수 스캔해 상품 하나당 ~40ms 든다(729개 상품에
    걸면 30초). 후보를 추리는 **싼 선필터**로 쓴다 — 브랜드가 카탈로그에 아예 없으면 그
    상품은 글로벌몰이 취급하지 않는다고 봐도 된다.
    """
    return frozenset(item.brand_key for item in _load_items() if item.brand_key)


def brand_in_catalog(brand: str) -> bool:
    """브랜드가 카탈로그에 있는지(부분일치 포함). match_oliveyoung 앞단의 싼 게이트."""
    key = normalize_key(brand or "")
    if not key:
        return False
    return any(key == c or key in c or c in key for c in catalog_brand_keys())


def _brands_match(q_brand_key, q_brand_tokens, c_brand_key, c_name_tokens) -> bool:
    # 브랜드키가 겹치면 일치(마츠키요와 동일). 단 상품 브랜드가 한글('오휘')이고 후보
    # 브랜드가 영문('OHUI')이라 키가 안 겹칠 수 있어, 상품 브랜드 토큰이 후보 상품명
    # 토큰과 겹치면(한글 브랜드가 상품명에 포함되는 경우) 일치로 본다.
    if q_brand_key and c_brand_key and (
        q_brand_key == c_brand_key
        or q_brand_key in c_brand_key
        or c_brand_key in q_brand_key
    ):
        return True
    return bool(q_brand_tokens & c_name_tokens)


def _score_tokens(q_brand_tokens, q_name_tokens, c_brand_tokens, c_name_tokens, brand_hit) -> float | None:
    """라인 토큰(브랜드 토큰 제외) 자카드 + 브랜드 보너스. 겹침 없으면 None.

    브랜드 토큰을 양쪽 상품명 토큰에서 빼고 계산해, 브랜드만 같고 라인이 다른 상품
    ('롬앤 쥬시래스팅틴트' vs '롬앤 글래스팅워터틴트')이 브랜드 이중계상으로 넘어오는
    오탐을 막는다. 라인이 다르면 구별 토큰이 안 겹쳐 낮은 점수가 된다.

    또한 양쪽 상품명에 제품종류(폼) 토큰이 모두 있는데 서로 겹치지 않으면(선크림 vs 토너,
    클렌저 vs 크림) 라인 접두사(예: '1025 독도')가 같아도 다른 제품이므로 기각한다. 한 브랜드
    라인의 여러 변형이 카탈로그의 단일 변형으로 잘못 매칭되던 오탐을 막는다(사용자 지적).
    """
    exclude = q_brand_tokens | c_brand_tokens
    ql = q_name_tokens - exclude
    il = c_name_tokens - exclude
    if not ql or not il:
        return None
    q_forms = _form_families(ql)
    c_forms = _form_families(il)
    if q_forms and c_forms and not (q_forms & c_forms):
        return None
    overlap = len(ql & il)
    if overlap == 0:
        return None
    score = overlap / len(ql | il)
    # 브랜드 미확인 매칭은 라인만으로 강하게 겹쳐야 채택(교차브랜드 오탐 방지).
    return score + (0.25 if brand_hit else -0.1)


def score_line(
    q_brand_key, q_brand_tokens, q_name_tokens, c_brand_key, c_brand_tokens, c_name_tokens
) -> float | None:
    """사전계산된 토큰셋으로 라인 유사도 점수를 낸다(없으면 None). 카탈로그/라이브 공용 코어."""
    brand_hit = _brands_match(q_brand_key, q_brand_tokens, c_brand_key, c_name_tokens)
    return _score_tokens(q_brand_tokens, q_name_tokens, c_brand_tokens, c_name_tokens, brand_hit)


def line_match_score(brand: str, name: str, cand_brand: str, cand_name: str) -> float | None:
    """(brand,name) 질의와 후보 상품(cand_brand,cand_name)의 라인 유사도 점수. 없으면 None.

    카탈로그 매칭과 국내몰 라이브 검색 결과 매칭이 같은 규칙을 쓰도록 공유한다.
    """
    q_name_tokens = tokens_for(name)
    if not q_name_tokens:
        return None
    return score_line(
        normalize_key(brand), tokens_for(brand), q_name_tokens,
        normalize_key(cand_brand), tokens_for(cand_brand), tokens_for(cand_name),
    )


@lru_cache(maxsize=8192)
def match_oliveyoung(brand: str, name: str, min_score: float = 0.5) -> OYMatch | None:
    """상품을 로컬 카탈로그와 조인해 최적 매칭을 반환한다(없으면 None). JP 글로벌몰 전용.

    카탈로그 3,100여 건을 전수 스캔해 호출당 ~77ms 든다(실측). 아이템매칭은 같은 후보에
    resolve 를 두 번(네이버 보강 전후) 돌리고 요청 간에도 같은 상품이 반복되므로 메모이즈한다.
    반환 OYMatch 는 읽기 전용으로만 쓸 것(호출부가 변형하면 캐시가 오염된다).
    """
    q_brand_key = normalize_key(brand)
    q_brand_tokens = tokens_for(brand)
    q_name_tokens = tokens_for(name)
    if not q_name_tokens:
        return None

    best: OYMatch | None = None
    best_score = 0.0
    for item in _load_items():
        # (a) 결합(영문+한글) 토큰 점수 — 기존 동작(정밀, 형제라인 오탐 방지).
        score = score_line(
            q_brand_key, q_brand_tokens, q_name_tokens,
            item.brand_key, item.brand_tokens, item.name_tokens,
        )
        if score is not None and score < min_score:
            score = None
        # (b) 결합이 문턱 미달이면 영문/한글 토큰셋으로 '따로' 재채점한다. 영문 쿼리가 한글 토큰에
        #     희석돼 놓치던 상품(예: espoir 'Pro Tailor'→카탈로그 'Be Velvet Foundation')을 살린다.
        #     단 구별(비-폼) 토큰이 2개 이상 겹칠 때만 인정해 형제라인 오탐은 계속 차단한다.
        if score is None:
            exclude = q_brand_tokens | item.brand_tokens
            ql = q_name_tokens - exclude
            for cnt in (item.name_en_tokens, item.name_kr_tokens):
                if not cnt:
                    continue
                s = score_line(
                    q_brand_key, q_brand_tokens, q_name_tokens,
                    item.brand_key, item.brand_tokens, cnt,
                )
                if s is None or s < min_score:
                    continue
                overlap = ql & (cnt - exclude)
                if sum(1 for t in overlap if not _form_families({t})) < 2:
                    continue
                score = s if score is None else max(score, s)
        if score is None:
            continue
        if best is None or score > best_score:
            best_score = score
            best = OYMatch(
                brand=item.brand,
                name_en=item.name_en,
                name_kr=item.name_kr,
                prdt_no=item.prdt_no,
                gds_cd=item.gds_cd,
                score=round(min(1.0, score), 3),
                image_url=item.image_url,
            )
    return best


# ── 남성 아이템매칭 소스 ────────────────────────────────────────────────────
# JP 남성은 상품 소스가 라쿠텐(일본 브랜드)뿐이라 올리브영 글로벌 버튼이 안 붙는다(J뷰티 제외 +
# 라쿠텐이 한국 남성 브랜드를 안 줌). 그래서 글로벌몰 카탈로그에서 '남성' 상품을 직접 뽑아
# 상품 카드로 노출한다(올리브영 JP 남성 고객 확보). 남성 판별: 전량 남성 브랜드 + 상품명 남성 신호.
#
# 판별 규칙은 국내몰 카탈로그(oliveyoung_kr_search.kr_male_catalog_items)도 그대로 쓴다 —
# 두 카탈로그가 '남성'을 다르게 세면 지역에 따라 카드가 들쭉날쭉해진다.
_MEN_CATALOG_BRAND_KEYS = {
    normalize_key(b) for b in ("dashu", "grafen", "ideal for men", "briall homme")
}
_MEN_NAME_RE = re.compile(r"homme|맨즈|옴므|포\s?맨|for\s?men|\bmen'?s?\b|남성|남자", re.I)


def is_male_product(brand: str, *names: str) -> bool:
    """상품이 남성용인지 — 전량 남성 브랜드이거나 이름에 남성 표기가 있으면 True.

    `names` 는 같은 상품의 표기 변형(한글명/영문명/일본어명)을 그대로 넘기면 된다.
    """
    if normalize_key(brand) in _MEN_CATALOG_BRAND_KEYS:
        return True
    return bool(_MEN_NAME_RE.search(" ".join([brand or "", *(n or "" for n in names)])))


def _parse_usd(raw: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", (raw or "").replace(",", ""))
    return float(m.group()) if m else 0.0


def _as_catalog_item(item: _OYItem) -> OYCatalogItem:
    return OYCatalogItem(
        brand=item.brand,
        brand_jp=item.brand_jp,
        name_kr=item.name_kr,
        name_en=item.name_en,
        name_jp=item.name_jp,
        prdt_no=item.prdt_no,
        image_url=item.image_url,
        price_usd=_parse_usd(item.sale_amt),
    )


def male_catalog_items() -> list[OYCatalogItem]:
    """글로벌몰 카탈로그의 '남성' 상품 목록(JP 남성 소스). 카탈로그 없으면 빈 리스트.

    ⚠ 이건 **글로벌몰**(prdtNo) 상품이라 링크도 글로벌몰로 나간다. KR 사용자에게는
      국내몰 쪽(oliveyoung_kr_search.kr_male_catalog_items)을 써야 한다.
    """
    return [
        _as_catalog_item(item)
        for item in _load_items()
        if is_male_product(item.brand, item.name_en, item.name_kr)
    ]


def catalog_items() -> list[OYCatalogItem]:
    """글로벌몰 카탈로그 전 상품(카드 소스).

    JP 올리브영 탭에서 **비어 있는 컬럼**(실측: 블러셔·네일 0건)을 메우는 후보 소스다.
    JP 후보는 라쿠텐 라이브 검색뿐인데 라쿠텐엔 한국 색조 브랜드가 거의 안 떠서, 검증만으로는
    그 컬럼이 영원히 빈다 — KR 쪽 _inject_kr_oliveyoung_catalog 와 같은 구조의 공백이다.
    """
    return [_as_catalog_item(item) for item in _load_items()]
