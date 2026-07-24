"""영유아·소아 바디케어 안전 게이트.

설계 원칙(BODY_CATEGORY_SPEC §11.6, 사용자 결정):
- 분류기가 아니라 '추천 시점'에 연령을 고려한다. 나이는 사용자가 설문에서 직접 고르는
  값이라, 성인 데이터로 학습된 분류기의 OOD 문제(영유아 학습데이터 0건)를 우회한다.
- 영유아 제품 커버리지가 얇고(KR 15~25건·JP 0) 분류기도 성인 기준이라, 정식 질환별 랭킹
  추천은 하지 않는다. '안내 우선 + 성분 검증된 순한 상품 소수 큐레이션'만 한다.

이 모듈은 '무엇을 소아에게 보여도 되는가'의 안전 기준만 정의한다. 추천 조립은 recommender 가
호출한다.
"""
from __future__ import annotations

import re

# 설문 age_group 중 소아로 취급하는 값. 성인 밴드(10s~50s)와 구분한다.
PEDIATRIC_AGE_GROUPS = frozenset({"baby", "child"})

BABY = "baby"    # 0~2세
CHILD = "child"  # 3~9세


def is_pediatric(age_group: str | None) -> bool:
    return (age_group or "").strip().lower() in PEDIATRIC_AGE_GROUPS


# 소아 바디에 올려도 되는 '순한 장벽·보습' 성분만. 나머지는 전부 배제한다(화이트리스트 방식).
# 근거: 아토피 관리 1차는 보습제. 콜로이달오트밀·페트롤라툼은 소아 습진에 근거 수준이 높다.
PEDIATRIC_SAFE_INGREDIENTS = frozenset({
    "Ceramide",
    "Panthenol",
    "Glycerin",
    "Petrolatum",
    "Shea Butter",
    "Squalane",
    "Colloidal Oatmeal",
    "Allantoin",
    "Hyaluronic Acid",
    "Dimethicone",
    "Jojoba Oil",
})

# 소아에게 올리면 안 되는 성분(액티브·자극). 하나라도 있으면 배제한다.
# 화이트리스트만으로도 걸러지지만, '순한 보습 + 살리실산' 같은 혼합 제품을 확실히 막는다.
PEDIATRIC_AVOID_INGREDIENTS = frozenset({
    "Retinol",
    "Salicylic Acid",
    "Glycolic Acid",
    "Lactic Acid",
    "Vitamin C",
    "Azelaic Acid",
    "Niacinamide",   # 고농도 미백 액티브 — 소아엔 불필요
    "Green Tea",     # 카페인·폴리페놀, 소아 필요성 낮음
    "Zinc",
    "Peptide",
})

# 향료·에센셜오일 신호(상품명). 영유아는 무향이 원칙이라 향 표기가 있으면 뺀다.
_FRAGRANCE_RE = re.compile(
    r"퍼퓸|프래그런스|향수|아로마|에센셜\s*오일|\b퍼퓸|파우더향|플로럴|시트러스향|"
    r"perfume|fragrance|parfum|essential\s*oil|scented|"
    r"香水|フレグランス|パルファム|エッセンシャルオイル",
    re.I,
)
# '무향/무향료' 명시는 안전 신호(있으면 향 배제 규칙을 통과시킨다).
_FRAGRANCE_FREE_RE = re.compile(
    r"무향|무\s*향료|저자극|fragrance[\s-]*free|unscented|無香料|低刺激", re.I
)


def has_fragrance_signal(name: str) -> bool:
    text = name or ""
    if _FRAGRANCE_FREE_RE.search(text):
        return False
    return bool(_FRAGRANCE_RE.search(text))


# 전성분 원문에서 향료·에센셜오일·향료알러젠을 잡는다. 상품명엔 '무향'이라 적어도
# 전성분에 향료 성분이 있으면 영유아엔 부적합. EU 지정 향료 알러젠 + 향료/정유 표기.
_FRAGRANCE_IN_INGREDIENTS_RE = re.compile(
    r"향료|착향제|정유|에센셜\s*오일|"
    # EU26 향료 알러젠(한글 표기)
    r"리모넨|리날룰|시트로넬올|제라니올|시트랄|쿠마린|유제놀|"
    r"아이소유제놀|벤질\s*(벤조에이트|살리실레이트|신나메이트|알코올)|"
    r"헥실신남알|아밀신남알|하이드록시시트로넬알|아니스\s*알코올|"
    r"파네솔|시트로넬롤|"
    # 에센셜오일(대표): 라벤더·페퍼민트·유칼립투스·로즈마리·티트리·시트러스 정유
    r"라벤더오일|페퍼민트오일|유칼립투스오일|로즈마리오일|티트리오일|"
    r"오렌지\s*오일|레몬\s*오일|자몽\s*오일|버가못\s*오일|로즈\s*오일",
    re.I,
)


def raw_ingredients_have_fragrance(raw_text: str) -> bool:
    return bool(raw_text) and bool(_FRAGRANCE_IN_INGREDIENTS_RE.search(raw_text))


def is_pediatric_safe(ingredient_names: set[str], product_name: str) -> bool:
    """소아에게 추천해도 되는 상품인지.

    요건(모두 충족):
      1) 성분 데이터가 있다(성분 우선 원칙 — 모르면 안 올린다).
      2) 배제 성분(액티브)이 하나도 없다.
      3) 모든 성분이 소아안전 화이트리스트 안에 있다.
      4) 상품명에 향료 신호가 없다(무향 명시는 예외).
    """
    if not ingredient_names:
        return False
    if ingredient_names & PEDIATRIC_AVOID_INGREDIENTS:
        return False
    if not ingredient_names <= PEDIATRIC_SAFE_INGREDIENTS:
        return False
    if has_fragrance_signal(product_name):
        return False
    return True


PEDIATRIC_GUIDANCE = (
    "영유아·소아 피부는 성인용 제품 추천 대상이 아닙니다. 이 결과는 참고용 안내이며 "
    "진단이 아닙니다. 아기 피부는 장벽이 약해 향료·색소·강한 액티브(레티놀·산·비타민C 등)를 "
    "피하고, 무향·저자극 보습제로 자주 보습하는 것이 기본입니다. 증상(붉음·진물·심한 건조·"
    "가려움)이 있으면 자가 판단 대신 소아과·피부과 상담을 권합니다. 아래는 성분이 확인된 "
    "순한 보습 제품 예시입니다."
)

PEDIATRIC_GUIDANCE_NO_PRODUCTS = (
    "영유아·소아 피부는 성인용 제품 추천 대상이 아닙니다. 향료·색소·강한 액티브를 피하고 "
    "무향·저자극 보습제로 자주 보습하되, 증상이 있으면 소아과·피부과 상담을 권합니다. "
    "현재 성분이 검증된 소아 적합 제품을 충분히 확보하지 못해 개별 추천은 제공하지 않습니다."
)
