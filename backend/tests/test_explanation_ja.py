"""추천 요약문의 일본어판.

수치·성분명·상품명이 끼는 조립형 문장이라 프론트 사전으로는 못 옮긴다.
그래서 서버가 두 벌을 만들어 내려준다(퍼스널컬러 skin_summary_ja 와 같은 방식).
일본몰 결과지에 이 문장이 한국어로 나갔다(제보 2026-08-06).
"""

from __future__ import annotations

import re

from app.schemas.api import SkinScores, SurveyInput
from app.services.recommender import (
    AGE_LABELS,
    AGE_LABELS_JA,
    SKIN_TYPE_LABELS,
    SKIN_TYPE_LABELS_JA,
    TARGET_LABELS,
    TARGET_LABELS_JA,
    build_explanation,
    build_explanation_ja,
)

HANGUL = re.compile(r"[가-힣]")


def _fixture():
    scores = SkinScores(acne=20, pore=89, wrinkle=30, redness=15, pigmentation=58, oiliness=48)
    survey = SurveyInput(gender="male", age_group="30s", skin_type="combination", concerns=[])
    return scores, survey, ["Niacinamide", "Lactic Acid"], ["COSRX Cleanser", "numbuzin No.3"]


def test_japanese_explanation_has_no_korean():
    scores, survey, ingredients, products = _fixture()
    text = build_explanation_ja(scores, survey, ingredients, products)
    assert not HANGUL.search(text), f"일본어판에 한국어가 남아 있습니다: {text}"


def test_japanese_explanation_keeps_numbers_and_proper_nouns():
    """수치와 성분명·상품명은 옮기지 않는다 — 고유명사를 번역하면 찾을 수 없다."""
    scores, survey, ingredients, products = _fixture()
    text = build_explanation_ja(scores, survey, ingredients, products)
    assert "89" in text and "58" in text
    for name in ingredients + products:
        assert name in text, f"{name} 이 일본어판에서 사라졌습니다"


def test_korean_and_japanese_cover_the_same_keys():
    """한 쪽만 늘어나면 그 항목이 일본어 모드에서 KeyError 나 한국어로 샌다."""
    assert set(TARGET_LABELS) == set(TARGET_LABELS_JA)
    assert set(SKIN_TYPE_LABELS) == set(SKIN_TYPE_LABELS_JA)
    assert set(AGE_LABELS) == set(AGE_LABELS_JA)


def test_japanese_labels_are_not_korean():
    for ko_map, ja_map in ((TARGET_LABELS, TARGET_LABELS_JA), (SKIN_TYPE_LABELS, SKIN_TYPE_LABELS_JA)):
        for key, ja in ja_map.items():
            assert not HANGUL.search(ja), f"{key} 의 일본어 라벨이 한국어입니다: {ja}"
            assert ja != ko_map[key]


def test_korean_explanation_is_unchanged():
    """일본어판을 추가하면서 한국어판이 바뀌면 안 된다."""
    scores, survey, ingredients, products = _fixture()
    text = build_explanation(scores, survey, ingredients, products)
    assert text.startswith("가장 두드러진 피부 신호는 모공 89")
    assert "30대 남성, 복합성 피부" in text
