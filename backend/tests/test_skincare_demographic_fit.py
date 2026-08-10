"""성분 근거가 '다른 사람 사례'로 나가던 것(2026-08-10).

코퍼스 답변은 사례 원문이라 **첫 문장이 그 사례 본인의 나이·성별·피부타입으로 시작한다**
("52세 복합성 피부의…"). 그런데 검색은 고민어만 보고 인구통계를 아예 안 봤다
(context_text 가 gender/age 를 안 쓴다). 그래서 34세 남성 화면에 "28세 여성분의 복합성
피부…"로 시작하는 근거가 붙었다 — 실측 제보.

여기서 고정하는 것은 두 가지다.
  1. 관련도가 엇비슷하면 **이 사람과 같은 사례**를 고른다.
  2. 그 선호가 **점수에는 섞이지 않는다.** 점수에 더하면 주제가 다른 사례도 인구통계만으로
     임계값(KNOWLEDGE_MIN_SCORE=6.0)을 넘어 '확신에 찬 오답'이 나간다 — 임계값을 2.0 에서
     6.0 으로 올린 이유가 바로 그것이라 되돌리면 안 된다.
"""

from __future__ import annotations

import json

import pytest

from app.services.skincare_ingredient_knowledge import (
    SkincareIngredientKnowledge,
    demographic_fit,
)


def _record(rid: str, gender: str, age: str, skin: str) -> dict:
    """고민·문구는 모두 같고 인구통계만 다른 사례들 — 순서 차이가 오직 그것에서만 나오게 한다."""
    return {
        "id": rid,
        "target_concern": "모공",
        "question": "모공과 피지 관리에 좋은 성분이 궁금합니다.",
        "answer": f"{age}세 {skin} 피부 {gender}분의 모공 관리에는 나이아신아마이드를 고려합니다.",
        "evidence_sources": [],
        "gender": gender,
        "age": age,
        "skin_type": skin,
        "skin_concerns": ["모공"],
        "external_factors": [],
    }


@pytest.fixture
def knowledge(tmp_path) -> SkincareIngredientKnowledge:
    records = [
        _record("f28", "여성", "28", "복합성"),
        _record("m34", "남성", "34", "복합성"),
        _record("m52", "남성", "52", "지성"),
    ]
    path = tmp_path / "skincare.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return SkincareIngredientKnowledge(path)


def _context(gender: str, age_group: str, skin_type: str) -> dict:
    return {"survey": {"gender": gender, "age_group": age_group, "skin_type": skin_type, "concerns": []}}


# ── 적합도 계산 ─────────────────────────────────────────────────────────────

def test_fit_counts_gender_age_and_skin_type():
    record = _record("m34", "남성", "34", "복합성")
    assert demographic_fit(record, _context("male", "30s", "combination")) == 3.0
    assert demographic_fit(record, _context("female", "30s", "combination")) == 2.0
    assert demographic_fit(record, _context("male", "40s", "combination")) == 2.0
    assert demographic_fit(record, _context("female", "20s", "oily")) == 0.0


def test_age_band_groups_fifties_and_above():
    """코퍼스에 60대까지 있는데 설문의 마지막 칸은 '50대 이상'이다."""
    assert demographic_fit(_record("x", "남성", "63", "지성"), _context("male", "50s", "oily")) == 3.0


def test_fit_is_zero_without_survey():
    assert demographic_fit(_record("x", "남성", "34", "복합성"), None) == 0.0
    assert demographic_fit(_record("x", "남성", "34", "복합성"), {"scores": {"pore": 90}}) == 0.0


def test_sensitive_skin_has_no_counterpart_in_the_corpus():
    """민감성은 코퍼스 타입에 없다 — 억지로 맞추지 않고 가점 0 이다."""
    record = _record("x", "남성", "34", "복합성")
    assert demographic_fit(record, _context("male", "30s", "sensitive")) == 2.0


# ── 순서 ────────────────────────────────────────────────────────────────────

def test_same_person_case_is_preferred(knowledge):
    matches = knowledge.search("모공 피지가 고민입니다", _context("male", "30s", "combination"))
    assert matches[0].record["id"] == "m34", [m.record["id"] for m in matches]


def test_preference_flips_with_the_person(knowledge):
    """같은 질문이라도 사람이 바뀌면 고르는 사례가 바뀐다(정렬이 실제로 문맥을 본다)."""
    matches = knowledge.search("모공 피지가 고민입니다", _context("female", "20s", "combination"))
    assert matches[0].record["id"] == "f28", [m.record["id"] for m in matches]


def test_scores_are_untouched_by_demographics(knowledge):
    """⚠ 점수에 섞이면 임계값(6.0)의 의미가 무너진다 — 순서만 바뀌어야 한다."""
    male = knowledge.search("모공 피지가 고민입니다", _context("male", "30s", "combination"))
    female = knowledge.search("모공 피지가 고민입니다", _context("female", "20s", "combination"))
    assert sorted(m.score for m in male) == sorted(m.score for m in female)


def test_topically_better_record_still_wins(knowledge, tmp_path):
    """인구통계가 주제를 이기면 안 된다 — 주제가 맞는 사례가 인구통계와 무관하게 앞선다."""
    records = [
        # 인구통계는 완전히 일치하지만 주제가 다르다.
        {
            "id": "off-topic-perfect-fit",
            "target_concern": "미백(색소침착/기미/칙칙함)",
            "question": "기미와 색소침착 관리가 궁금합니다.",
            "answer": "미백은 자외선 차단과 비타민C 유도체를 함께 고려합니다.",
            "evidence_sources": [],
            "gender": "남성", "age": "34", "skin_type": "복합성",
            "skin_concerns": ["색소침착"], "external_factors": [],
        },
        # 주제는 정확히 맞지만 인구통계는 전혀 다르다.
        _record("on-topic-no-fit", "여성", "63", "건성"),
    ]
    path = tmp_path / "mixed.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    mixed = SkincareIngredientKnowledge(path)

    matches = mixed.search("모공과 피지가 고민입니다", _context("male", "30s", "combination"))
    assert matches[0].record["id"] == "on-topic-no-fit", [m.record["id"] for m in matches]
