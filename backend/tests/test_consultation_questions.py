"""상담 질문 리스트(설계안 §16).

이 기능의 성격이 중요하다: **시술을 권하는 게 아니라 사용자가 물어볼 것을 준다.**
그래서 의료광고 법무 회신 전에도 넣을 수 있다 — 무엇을 하라고 말하지 않는다.
테스트도 그 성격을 지킨다(시술명·비용이 새어 들어가면 전제가 무너진다).
"""

import re

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
def test_never_names_a_procedure(concerns: list[str] | None) -> None:
    """시술명은 쓰지 않는다(medical_ad_working_assumptions.md).

    이름을 대는 순간 '질문을 줄 뿐'이 아니라 그 시술을 가리키는 것이 된다.
    """
    banned = ["보톡스", "필러", "리프팅", "절골", "양악", "안면윤곽", "쌍꺼풀", "코성형", "지방이식"]
    for question in consultation_questions(concerns, referral_urgent=True):
        for word in banned:
            assert word not in question, f"시술명 '{word}' 가 들어 있습니다: {question}"


@pytest.mark.parametrize("concerns", [None, ["코 라인"], ["윤곽·얼굴형"]])
def test_never_states_an_amount(concerns: list[str] | None) -> None:
    """막아야 할 것은 '비용이라는 단어'가 아니라 **금액**이다.

    ⚠ 예전 검사는 금지어에 '비용은'을 넣어 두었는데, 비용을 **묻는** 질문
    ("총 비용이 얼마인가요?")이 조사 차이로 우연히 통과했다. 통과한 건 맞지만
    검사가 의도를 표현하지 못한 것이라 규칙을 다시 썼다.

    우리가 금액을 말하면 광고가 되고, 사용자가 묻게 하면 안 된다(§6).
    """
    amount = re.compile(r"\d[\d,]*\s*(원|만원|엔|円|만\s*원)")
    for question in consultation_questions(concerns, referral_urgent=True):
        assert not amount.search(question), f"금액이 들어 있습니다: {question}"


def test_cost_is_asked_not_stated() -> None:
    """비용은 **묻는다**. 가격 데이터가 없기도 하고, 표시하면 광고 판정의 핵심 요소가 된다(§6)."""
    questions = consultation_questions(["코 라인"])
    assert any("총 비용" in q and q.rstrip().endswith("?") for q in questions), (
        "비용을 묻는 질문이 없습니다 — 사용자가 상담에서 확인할 방법이 사라진다"
    )
    # 추가 청구 항목까지 묻게 한다. 총액만 물으면 마취·검사·재수술을 나중에 알게 된다.
    assert any("따로 청구" in q for q in questions)


def test_questions_are_questions() -> None:
    """'~하세요'가 아니라 물음이어야 한다. 지시문이 되면 우리가 판단한 것이 된다."""
    for question in consultation_questions(["코 라인"], referral_urgent=True):
        assert question.rstrip().endswith(("?", "습니다.", "니다.")), question
