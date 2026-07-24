"""상품 → 루틴 단계 분류 (품질 게이트).

루틴 골격: 클렌저 → 토너 → 세럼 → 보습(로션/크림) → 선크림.
6단계 중 하나로 '확실히' 분류되는 상품만 추천 후보가 된다. 분류 불가/잡음(헤어·키트·바디 등)은
None → 추천에서 제외. 설계 근거: docs/ROUTINE_RECOMMENDATION_SPEC.md

순수 함수라 DB 없이 단위테스트 가능.
"""
from __future__ import annotations

import re

from app.services.body_categories import ALL_CATEGORIES as NON_FACE_CATEGORIES

# 로션/크림은 분류상 별개 단계(상품은 둘 중 하나). '보습 택1'은 추천 조립 단계에서 처리한다.
ROUTINE_STEPS = ("cleanser", "toner", "serum", "lotion", "cream", "sunscreen")

# 1) 명시 카테고리 → 단계 (소문자 비교)
_EXPLICIT: dict[str, str] = {
    "cleanser": "cleanser", "cleansers": "cleanser",
    "toner": "toner", "pads": "toner",
    "serum": "serum", "essence": "serum", "ampoule": "serum",
    "treatment": "serum", "treatments": "serum",
    "blemish & acne treatments": "serum", "acne & blemish treatments": "serum",
    "lotion": "lotion",
    "cream": "cream", "moisturizers": "cream",
    "sunscreen": "sunscreen",
}

# 2) 명시 제외 카테고리 (핵심 루틴 5단계 밖)
_EXCLUDE_CATEGORIES: frozenset[str] = frozenset({
    "mask", "sheet masks", "facial masks", "patches", "gift set",
    "body moisturizers", "face", "nose pack", "hair wash", "eye",
    "bath & shower", "after sun care",
})

# 3) 이름으로 재분류할 카테고리
_NAME_INFER_CATEGORIES: frozenset[str] = frozenset({"skincare", "balm", "gel"})

# 잡음 — 카테고리 불문 최우선 제외(품질 게이트). 헤어·바디·키트·색조메이크업·아이케어·면도 등.
# 명시 카테고리('lotion' 이지만 'Body Lotion', 'cream' 이지만 'Eye Cream')도 여기서 걸러진다.
_BLOCK = re.compile(
    r"hair|shampoo|conditioner|hairspray|styling|mousse|"
    r"frizz|volumiz|volumis|straighten|\bcurl\b|curly|blowout|blow\s?dry|detangl|"
    r"split\s?end|heat\s?protect|dandruff|pomade|비듬|곱슬|"
    r"\bkit\b|\bset\b|\bbody\b|shower|\bbath\b|\bnail\b|\blip\b|"
    r"perfume|fragrance|deodorant|shave|scalp|leave[\s-]?in|두피|"
    # 색조 메이크업 (SPF 파운데이션 등이 선크림으로 오분류되는 것 방지)
    r"foundation|concealer|\bcushion\b|tint|primer|highlighter|bronz|\bblush\b|gloss|"
    r"lipstick|mascara|eyeliner|eye\s?shadow|\bbb\s?cream\b|\bcc\s?cream\b|"
    r"\bbrow\b|eyebrow|\blash(?:es)?\b|눈썹|속눈썹|"
    # 아이케어 = 별도 단계(핵심 5단계 밖)
    r"eye\s?(?:cream|serum|balm|gel|patch|care)|아이\s?(?:크림|세럼|패치)|"
    r"헤어|샴푸|린스|바디|샤워|네일|향수|파운데이션|쿠션|틴트",
    re.I,
)

# 단계 키워드 (위→아래 우선, 첫 매치 채택). 'skin/스킨'은 노이즈(skincare 등)라 토너에서 제외.
_NAME_RULES: tuple[tuple[str, str], ...] = (
    ("sunscreen", r"spf|sunscreen|sun\s?screen|자외선|선크림|선블록|선스틱|톤업\s?선|"
                  r"sun\s?(?:stick|cream|milk|fluid|gel|serum|essence|cushion|block)|"
                  r"uv\s?(?:protect|block|shield|cut|care|defense)"),
    ("cleanser",  r"cleans|클렌징|클렌저|클렌즈|foam|\bwash\b|폼클렌|세안|remover|리무버|micellar"),
    ("toner",     r"\btoner\b|토너|softener|\bmist\b|미스트|\bpad\b|패드|toning|토닝"),
    ("serum",     r"serum|세럼|essence|에센스|ampoule|앰플|treatment|\bpeel\b|필링|exfoliat|각질|"
                  r"booster|부스터|dark\s?spot|\bspot\b|concentrate|retinoid|retinol|retinal"),
    ("lotion",    r"lotion|로션|emulsion|에멀"),
    ("cream",     r"cream|크림|moistur|모이스|butter|버터|nourish|\bbalm\b|hydrat"),
)

_CLEANSING_NAME = re.compile(r"cleans|클렌징|makeup|메이크업|remover|리무버|cleansing\s?oil", re.I)

# 강한 이름 신호: 상품 카테고리 라벨이 잘못됐을 때(예: 'cream'인데 이름이 '...Toner')
# 이름을 우선한다. 오분류가 명백한 제품 타입만(순서=우선).
_STRONG_NAME: tuple[tuple[str, str], ...] = (
    ("sunscreen", r"sunscreen|\bspf\s?\d|선크림|선블록|자외선\s?차단|uv\s?(?:protect|block|shield)"),
    ("cleanser",  r"\bcleanser\b|cleansing\s?(?:foam|gel|oil|balm|water|milk)|클렌징\s?(?:폼|오일|워터)|폼\s?클렌|micellar"),
    ("serum",     r"retinoid|retinol|retinal"),
    ("toner",     r"\btoner\b|토너"),
)


def _strong_name_step(name: str) -> str | None:
    for step, pattern in _STRONG_NAME:
        if re.search(pattern, name, re.I):
            return step
    return None


def _infer_from_name(name: str) -> str | None:
    if not name or _BLOCK.search(name):
        return None
    for step, pattern in _NAME_RULES:
        if re.search(pattern, name, re.I):
            return step
    return None


def _infer_balm_gel(name: str) -> str | None:
    # balm/gel: 클렌징 성격이면 클렌저, 아니면 보습(크림). 헤어젤 등 잡음은 제외.
    if name and _BLOCK.search(name):
        return None
    if name and _CLEANSING_NAME.search(name):
        return "cleanser"
    return "cream"


def classify_routine_step(category: str | None, name: str | None) -> str | None:
    """상품을 루틴 단계(cleanser/toner/serum/lotion/cream/sunscreen) 중 하나로 분류.

    확실치 않으면 None → 추천 후보에서 제외(품질 게이트).
    """
    cat = (category or "").strip().lower()
    nm = name or ""
    # 바디·핸드·풋 카테고리(body.* / hand.* / foot.*)는 얼굴 루틴 단계가 아니다.
    # 아래 _STRONG_NAME 이 카테고리보다 먼저 도는 구조라, 여기서 끊지 않으면 이름에
    # 바디 단어가 없는 바디 상품이 얼굴 컬럼에 올라온다(실측 16건: ILLIYOON 아토
    # 젠틀 스킨 클렌저 → 얼굴 클렌저, 바디 선크림 → 얼굴 선크림).
    if cat in NON_FACE_CATEGORIES:
        return None
    # 잡음/비-루틴(헤어·바디·메이크업·아이·면도)은 카테고리 불문 최우선 제외.
    if nm and _BLOCK.search(nm):
        return None
    if cat in _EXCLUDE_CATEGORIES:
        return None
    # 명백한 이름 신호는 잘못된 카테고리 라벨을 이긴다('cream'라벨인데 이름이 'Toner' 등).
    strong = _strong_name_step(nm)
    if strong:
        return strong
    if cat in _EXPLICIT:
        return _EXPLICIT[cat]
    if cat in ("balm", "gel"):
        return _infer_balm_gel(nm)
    if cat in ("skincare", ""):
        return _infer_from_name(nm)
    return None  # 알 수 없는 카테고리 → 제외


def product_routine_step(product) -> str | None:
    """Product ORM 객체 편의 래퍼."""
    return classify_routine_step(getattr(product, "category", None), getattr(product, "name", None))
