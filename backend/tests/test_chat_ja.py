"""상담(챗봇) 답변의 일본어판(2026-08-07).

상담 화면은 일본어 모드에도 그대로 열려 있는데, 답변 경로가 **전부 한국어**였다:
  · LLM 프롬프트가 "한국어로 답합니다"를 명시
  · 폴백 지식베이스(KNOWLEDGE_BASE)·범위 밖 안내·컨텍스트 힌트 모두 한국어 문장뿐
일본어로 물어도 한국어 답이 돌아왔다.

성분 코퍼스는 8,341건 전량 번역돼 있으므로 일본어 근거를 그대로 쓸 수 있다. 번역본이 없는
문제성 피부 코퍼스는 일본어 경로에서 아예 쓰지 않는다 — 근거 문단이 하나 없는 것이
한국어가 섞이는 것보다 낫다(이 저장소의 일관된 원칙).
"""

from __future__ import annotations

import re

import pytest

from app.services import chatbot, llm_consult
from app.services.chatbot import (
    KNOWLEDGE_BASE,
    KNOWLEDGE_BASE_JA,
    OUT_OF_SCOPE_ANSWER,
    OUT_OF_SCOPE_ANSWER_JA,
    TARGET_LABELS,
    TARGET_LABELS_JA,
    answer_skin_question,
)

HANGUL = re.compile(r"[가-힣]")


class _FakeSession:
    """DB 없이 답변 경로만 본다(ChatHistory 기록은 이 테스트의 관심사가 아니다)."""

    def add(self, _obj):  # noqa: D102
        pass

    def commit(self):  # noqa: D102
        pass


# ── 표가 어긋나지 않는지 ────────────────────────────────────────────────────

def test_knowledge_base_and_labels_cover_the_same_keys():
    assert {key for key, _ in KNOWLEDGE_BASE} == set(KNOWLEDGE_BASE_JA)
    assert set(TARGET_LABELS) == set(TARGET_LABELS_JA)


@pytest.mark.parametrize("text", list(KNOWLEDGE_BASE_JA.values()) + list(TARGET_LABELS_JA.values()))
def test_japanese_tables_have_no_korean(text):
    assert not HANGUL.search(text), f"일본어 표에 한국어가 남아 있습니다: {text}"


def test_out_of_scope_answer_ja_is_japanese():
    assert not HANGUL.search(OUT_OF_SCOPE_ANSWER_JA)
    assert OUT_OF_SCOPE_ANSWER_JA != OUT_OF_SCOPE_ANSWER


# ── 답변 경로 ───────────────────────────────────────────────────────────────

@pytest.fixture
def no_llm(monkeypatch):
    """LLM 을 끈 상태의 폴백 경로를 본다(키 없는 환경·호출 실패와 같은 경로)."""
    monkeypatch.setattr(llm_consult, "is_enabled", lambda: False)


def test_out_of_scope_question_answers_in_japanese(no_llm):
    result = answer_skin_question(_FakeSession(), "旅行のおすすめは？", lang="ja")
    assert not HANGUL.search(result.answer), result.answer
    assert result.answer == OUT_OF_SCOPE_ANSWER_JA


def test_keyword_fallback_answers_in_japanese(no_llm):
    # 'retinol' 키워드는 KNOWLEDGE_BASE 에 있다 — 일본어 모드면 일본어 문장이 나가야 한다.
    result = answer_skin_question(_FakeSession(), "retinol の使い方は？", lang="ja")
    assert not HANGUL.search(result.answer), result.answer
    assert KNOWLEDGE_BASE_JA["retinol"] in result.answer


def test_keyword_fallback_context_hint_is_japanese(no_llm):
    context = {"scores": {"pore": 88.0, "wrinkle": 51.0, "acne": 12.0}}
    result = answer_skin_question(_FakeSession(), "niacinamide について", context=context, lang="ja")
    assert not HANGUL.search(result.answer), result.answer
    assert TARGET_LABELS_JA["pore"] in result.answer  # 毛穴


def test_korean_path_is_unchanged(no_llm):
    """일본어판을 추가하면서 한국어 답변이 바뀌면 안 된다."""
    result = answer_skin_question(_FakeSession(), "retinol 어떻게 쓰나요?", lang="ko")
    assert KNOWLEDGE_BASE[4][1] in result.answer
    assert answer_skin_question(_FakeSession(), "여행 추천해줘", lang="ko").answer == OUT_OF_SCOPE_ANSWER


def test_japanese_never_falls_back_to_korean_problem_skin_corpus(no_llm, monkeypatch):
    """문제성 피부 코퍼스는 일본어판이 없다 — 일본어 경로에서 그 답이 나가면 안 된다."""
    called = {"n": 0}

    class _AlwaysMatches:
        def search(self, *_a, **_k):
            called["n"] += 1
            return []

    monkeypatch.setattr(chatbot, "get_problem_skin_knowledge", lambda: _AlwaysMatches())
    answer_skin_question(_FakeSession(), "肌が赤くなります", lang="ja")
    assert called["n"] == 0, "일본어 상담이 한국어 전용 코퍼스를 조회했습니다"


# ── 일본어 질문이 근거를 실제로 찾는지 ──────────────────────────────────────
# 코퍼스 색인이 한국어 토큰이라, 일본어 질문은 **점수가 그냥 0** 이었다(실측 2026-08-07).
# 답변은 나가지만 '참고 근거'가 통째로 빠진다 — 이 서비스가 신뢰도의 핵심 자산으로 두는 것이
# 일본 사용자에게만 없었다는 뜻이다.

@pytest.mark.parametrize(
    "question,expected_concern",
    [
        ("毛穴と皮脂が気になります", "毛穴"),
        ("シワとハリの低下が気になります", "シワ"),
        ("ニキビが繰り返します", "ニキビ"),
        ("頬の赤みが気になります", "赤み"),
        ("シミやくすみを何とかしたい", "美白"),
        ("乾燥と角質が気になります", "角質"),
    ],
)
def test_japanese_question_retrieves_japanese_evidence(question, expected_concern):
    from app.services.chatbot import KNOWLEDGE_MIN_SCORE
    from app.services.skincare_ingredient_knowledge import (
        build_skincare_answer_ja,
        get_skincare_ingredient_knowledge,
    )

    matches = get_skincare_ingredient_knowledge().search(question, None, limit=1)
    assert matches, f"일본어 질문이 코퍼스에 하나도 안 걸립니다: {question}"
    assert matches[0].score >= KNOWLEDGE_MIN_SCORE, (
        f"점수 {matches[0].score:.2f} 가 채택 임계값 미만 — 근거 없이 답하게 됩니다: {question}"
    )
    answer, sources = build_skincare_answer_ja(matches)
    assert answer and not HANGUL.search(answer), answer
    assert sources and expected_concern in sources[0], sources


def test_korean_question_scoring_is_unchanged():
    """일본어 힌트를 붙이면서 한국어 검색이 흔들리면 안 된다."""
    from app.services.skincare_ingredient_knowledge import get_skincare_ingredient_knowledge

    knowledge = get_skincare_ingredient_knowledge()
    for question in ("모공과 피지가 고민이에요", "주름과 탄력 저하"):
        matches = knowledge.search(question, None, limit=1)
        assert matches and matches[0].score > 15, question


def test_ja_hint_leaves_korean_query_untouched():
    from app.services.skincare_ingredient_knowledge import SkincareIngredientKnowledge as K

    assert K._with_ja_hints("모공과 피지가 고민이에요") == "모공과 피지가 고민이에요"
    assert "모공" in K._with_ja_hints("毛穴が気になります")


# ── LLM 프롬프트 ────────────────────────────────────────────────────────────

def test_llm_system_prompt_switches_language(monkeypatch):
    """프롬프트가 답변 언어를 정한다 — 한국어판은 '한국어로 답합니다'를 명시하고 있었다."""
    seen: dict = {}

    class _FakeChat:
        class completions:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                seen.update(kwargs)
                class _M:
                    content = "OK"
                class _C:
                    message = _M()
                class _R:
                    choices = [_C()]
                return _R()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(llm_consult, "_client", lambda: (_FakeClient(), _Settings()))

    class _Settings:
        openai_model = "gpt-4.1-mini"

    llm_consult.generate("毛穴が気になります", [], None, lang="ja")
    system = seen["messages"][0]["content"]
    assert system == llm_consult.SYSTEM_PROMPT_JA
    assert not HANGUL.search(system), "일본어 프롬프트에 한국어가 남아 있습니다"
    assert "質問: 毛穴が気になります" in seen["messages"][1]["content"]

    llm_consult.generate("모공이 고민이에요", [], None, lang="ko")
    assert seen["messages"][0]["content"] == llm_consult.SYSTEM_PROMPT
