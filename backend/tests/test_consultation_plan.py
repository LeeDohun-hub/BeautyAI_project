"""상담 후보·비용·회복(설계안 §7·§8).

설계안이 요구한 '예상 비용 범위'를 구현한 것인데, **금액이 아니라 티어**다.
§8 이 그렇게 정했고("확정 견적이 아니라 범위로 제공한다"), 실제 금액은 병원·국가·재료·
마취 방식·개인 상태에 따라 달라져 숫자로 쓸 수 없다.

여기서 지키는 것:
  · 금액이 새어 들어가지 않는다
  · '필요하다'가 아니라 '후보'로 말한다(설계안 §5 가 금지한 문장들)
  · 화면 카드 id 와 매핑이 어긋나지 않는다 — 어긋나면 결과지가 조용히 빈다
"""

import re

import pytest

from app.services.virtual_surgery_simulator import (
    CARD_PRESETS,
    CONSULT_CANDIDATE_NOTE,
    CONSULT_COST_NOTE,
    CONSULT_TIERS,
    consultation_plan,
)

CARD_IDS = [preset["id"] for preset in CARD_PRESETS]
TIER_ORDER = [key for key, _label in CONSULT_TIERS]


def _plan_texts(plan: dict) -> list[str]:
    """계획에 들어 있는 **모든 문자열**을 평평하게 편다.

    금액·단정 표현 검사가 tiers 안쪽까지 봐야 한다 — 겉만 훑으면 시술 후보 목록이
    검사에서 빠져, 정작 위험한 문구가 그 안에 있어도 통과한다.
    """
    texts: list[str] = []
    for key, value in plan.items():
        if key == "tiers":
            for tier in value:
                texts.append(tier["label"])
                texts.extend(tier["items"])
        elif isinstance(value, list):
            texts.extend(str(v) for v in value)
        else:
            texts.append(str(value))
    return texts


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_every_card_has_a_plan(card_id: str) -> None:
    """카드는 있는데 계획이 없으면 결과지의 그 칸이 조용히 빈다."""
    plan = consultation_plan(card_id)
    assert plan, f"{card_id} 카드에 상담 계획이 없습니다"
    for key in ("cost_tier", "recovery", "difficulty", "caution"):
        assert plan[key], f"{card_id}: {key} 가 비어 있습니다"
    assert plan["tiers"], f"{card_id}: 상담 후보가 하나도 없습니다"


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_tiers_go_from_light_to_heavy(card_id: str) -> None:
    """설계안 §9: '사용자가 바로 수술로 향하지 않도록' — **순서가 곧 메시지다.**

    메이크업 → 피부과·쁘띠 → 성형외과 → 수술. 뒤집히면 의도가 반대가 된다.
    """
    keys = [tier["key"] for tier in consultation_plan(card_id)["tiers"]]
    positions = [TIER_ORDER.index(k) for k in keys]
    assert positions == sorted(positions), f"{card_id}: 단계 순서가 뒤집혔습니다 {keys}"


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_light_option_always_comes_first(card_id: str) -> None:
    """모든 카드에 **메이크업 단계가 있어야** 한다.

    없으면 첫 줄부터 시술 이야기로 시작해, 설계안이 막으려던 흐름이 된다.
    """
    keys = [tier["key"] for tier in consultation_plan(card_id)["tiers"]]
    assert keys and keys[0] == "makeup", f"{card_id}: 첫 단계가 메이크업이 아닙니다 {keys}"


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_empty_tiers_are_dropped(card_id: str) -> None:
    """비어 있는 단계는 안 보낸다 — '해당 없음'이 줄줄이 있으면 있는 항목이 묻힌다."""
    for tier in consultation_plan(card_id)["tiers"]:
        assert tier["items"], f"{card_id}: 빈 단계 '{tier['key']}' 가 실렸습니다"


def test_unknown_card_returns_empty_not_a_guess() -> None:
    """모르는 카드에 없는 정보를 지어내면 안 된다."""
    assert consultation_plan("does-not-exist") == {}
    assert consultation_plan(None) == {}


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_no_amounts_anywhere(card_id: str) -> None:
    """비용은 티어로만 말한다. 금액이 들어가면 설계안 §8 을 어기는 것이다."""
    amount = re.compile(r"\d[\d,]*\s*(원|만원|엔|円|달러|\$)")
    plan = consultation_plan(card_id)
    for text in _plan_texts(plan):
        assert not amount.search(text), f"{card_id} 에 금액이 있습니다: {text}"


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_never_says_a_procedure_is_needed(card_id: str) -> None:
    """설계안 §5 가 금지한 표현. '후보'여야 하고 '필요하다'면 안 된다."""
    banned = ["필요합니다", "해야 합니다", "받으면 예뻐", "권장합니다", "추천드립니다"]
    plan = consultation_plan(card_id)
    for text in _plan_texts(plan):
        for word in banned:
            assert word not in text, f"{card_id} 에 단정 표현 '{word}': {text}"


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_no_markdown_in_user_facing_text(card_id: str) -> None:
    """화면은 이 문자열을 **평문으로 그대로** 출력한다(JSX 는 마크다운을 해석하지 않는다).

    실제로 '**후보**' 가 별표째 노출됐다 — 결과지처럼 병원에 들고 가는 화면이라
    이런 게 남으면 완성도가 그대로 보인다. 눈으로는 잘 안 잡히므로 검사로 둔다.
    """
    for text in _plan_texts(consultation_plan(card_id)):
        for mark in ("**", "__", "`"):
            assert mark not in text, f"{card_id} 에 마크다운 '{mark}': {text}"


def test_notes_are_attached_to_every_plan() -> None:
    """비용 주석·후보 주석이 빠지면 티어만 남아 확정 가격처럼 읽힌다."""
    for card_id in CARD_IDS:
        plan = consultation_plan(card_id)
        assert plan["cost_note"] == CONSULT_COST_NOTE
        assert plan["candidate_note"] == CONSULT_CANDIDATE_NOTE


def test_frontend_card_ids_match() -> None:
    """프론트가 고른 카드 id 로 계획을 찾는다. 어긋나면 결과지가 조용히 빈다."""
    from pathlib import Path

    app_tsx = Path(__file__).resolve().parents[2] / "frontend" / "src" / "App.tsx"
    source = app_tsx.read_text(encoding="utf-8")
    for card_id in CARD_IDS:
        assert f"id: '{card_id}'" in source, f"프론트에 카드 '{card_id}' 가 없습니다"
