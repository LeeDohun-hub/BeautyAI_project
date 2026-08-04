"""상담 질문 리스트(설계안 §16).

이 기능의 성격이 중요하다: **시술을 권하는 게 아니라 사용자가 물어볼 것을 준다.**
그래서 의료광고 법무 회신 전에도 넣을 수 있다 — 무엇을 하라고 말하지 않는다.
테스트도 그 성격을 지킨다(시술명·비용이 새어 들어가면 전제가 무너진다).
"""

import pytest

from app.services.virtual_surgery_simulator import (
    _QUESTIONS_ALWAYS,
    _QUESTION_IF_REFERRAL,
    consultation_questions,
)


def test_always_questions_are_included_even_with_no_input() -> None:
    """부위를 안 골랐어도 안전 질문은 나온다 — 사용자가 먼저 떠올리기 어려운 것들이다."""
    questions = consultation_questions(None)
    for must in _QUESTIONS_ALWAYS:
        assert must in questions


def test_referral_question_comes_first() -> None:
    """진료 안내가 있으면 그것부터 묻게 한다. 미용 상담이 진료보다 앞서면 안 된다."""
    questions = consultation_questions(["코 라인"], referral_urgent=True)
    assert questions[0] == _QUESTION_IF_REFERRAL


def test_selected_concern_changes_the_questions() -> None:
    """고른 부위가 결과에 반영되지 않으면, 1단계 선택이 또 무의미해진다
    (2026-08-03 에 같은 문제를 이미 겪었다 — 선택값이 백엔드로 안 갔다)."""
    jaw = consultation_questions(["윤곽·얼굴형"])
    nose = consultation_questions(["코 라인"])
    assert jaw != nose
    assert any("골격" in q for q in jaw)
    assert any("메이크업" in q for q in nose)


def test_falls_back_to_analysis_when_nothing_selected() -> None:
    """1단계를 건너뛴 사용자도 자기 분석에 맞는 질문을 받는다."""
    questions = consultation_questions([], recommendations=[{"category": "blemish"}])
    assert any("색소침착" in q for q in questions)


def test_no_duplicates() -> None:
    """부위를 여러 개 고르면 카테고리가 겹친다(윤곽·턱끝·광대 → 전부 face_frame)."""
    questions = consultation_questions(["윤곽·얼굴형", "턱끝·하관", "광대·볼 폭"])
    assert len(questions) == len(set(questions))


@pytest.mark.parametrize("concerns", [None, [], ["코 라인"], ["점·잡티 제거"], ["윤곽·얼굴형"]])
def test_never_names_a_procedure_or_price(concerns: list[str] | None) -> None:
    """법무 회신 전까지 시술명·비용은 금지다(medical_ad_working_assumptions.md).

    질문 문구에 그것들이 섞이면 '질문을 줄 뿐'이라는 전제가 무너진다.
    """
    banned = [
        "보톡스", "필러", "리프팅", "절골", "양악", "안면윤곽", "쌍꺼풀", "코성형",
        "만원", "비용은", "가격", "원대",
    ]
    for question in consultation_questions(concerns, referral_urgent=True):
        for word in banned:
            assert word not in question, f"금지어 '{word}' 가 들어 있습니다: {question}"


def test_questions_are_questions() -> None:
    """'~하세요'가 아니라 물음이어야 한다. 지시문이 되면 우리가 판단한 것이 된다."""
    for question in consultation_questions(["코 라인"], referral_urgent=True):
        assert question.rstrip().endswith(("?", "습니다.", "니다.")), question
