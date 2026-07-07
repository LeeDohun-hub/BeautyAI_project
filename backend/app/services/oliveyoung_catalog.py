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
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.services.matsukiyo_matcher import normalize_key, tokens_for

# 크롤러 산출물. FIELDNAMES는 scripts/crawl_oliveyoung_global.py 와 일치.
_CATALOG_FILENAME = "oliveyoung_global_products.csv"

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
                )
            )
    return tuple(items)


def clear_cache() -> None:
    """테스트/재크롤 후 인메모리 인덱스 초기화."""
    _load_items.cache_clear()


def catalog_available() -> bool:
    """카탈로그 CSV가 로드되어 최소 1개 항목이 있으면 True.

    False면 호출부는 라이브 검색 링크(기존 동작)로 폴백해야 한다(크롤 전 그레이스풀).
    """
    return bool(_load_items())


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
    """
    exclude = q_brand_tokens | c_brand_tokens
    ql = q_name_tokens - exclude
    il = c_name_tokens - exclude
    if not ql or not il:
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


def match_oliveyoung(brand: str, name: str, min_score: float = 0.5) -> OYMatch | None:
    """상품을 로컬 카탈로그와 조인해 최적 매칭을 반환한다(없으면 None). JP 글로벌몰 전용."""
    q_brand_key = normalize_key(brand)
    q_brand_tokens = tokens_for(brand)
    q_name_tokens = tokens_for(name)
    if not q_name_tokens:
        return None

    best: OYMatch | None = None
    best_score = 0.0
    for item in _load_items():
        score = score_line(
            q_brand_key, q_brand_tokens, q_name_tokens,
            item.brand_key, item.brand_tokens, item.name_tokens,
        )
        if score is None or score < min_score:
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
            )
    return best
