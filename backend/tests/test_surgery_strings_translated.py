"""성형 모듈이 화면으로 보내는 문자열이 일본어 번역을 갖고 있는지 검사한다.

왜 테스트로 두는가
------------------
2026-08-04 발견: 법적 고지·의료 선별 안내·얼굴형 요약이 프론트에서 t() 없이 그대로
출력돼, **일본 사용자가 한국어 법적 고지를 보고 있었다.** 출시 국가가 한국+일본이라
그냥 두면 안 되는 상태였는데, 화면은 정상으로 보이고 테스트도 전부 통과했다.

이 부류는 백엔드에서 문구를 한 글자만 고쳐도 다시 깨진다(키가 문자열 자체이기 때문).
사람이 매번 확인할 수 없으므로 여기서 잡는다.
"""

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
I18N = BACKEND.parent / "frontend" / "src" / "i18n.ts"
SIMULATOR = BACKEND / "app" / "services" / "virtual_surgery_simulator.py"
FACE_SHAPE = BACKEND / "app" / "services" / "face_shape_analyzer.py"


def _i18n_text() -> str:
    return I18N.read_text(encoding="utf-8")


def _korean_literals(path: Path, pattern: str) -> list[str]:
    source = path.read_text(encoding="utf-8")
    return [m.group(1) for m in re.finditer(pattern, source) if re.search(r"[가-힣]", m.group(1))]


def _simulator_literals() -> list[str]:
    """검사 대상 문자열.

    ⚠ 고지는 **모듈 상수를 직접 임포트**한다. 소스를 정규식으로 훑던 때, 문장을 늘리면서
    여러 줄 문자열이 되자 정규식이 못 잡아 검사 대상에서 조용히 빠졌다(29건 → 28건).
    '통과'로 보였지만 실제로는 검사를 안 한 것이었다. 값을 직접 읽으면 그 일이 없다.
    """
    from app.services.virtual_surgery_simulator import (
        DISCLAIMER_FULL,
        DISCLAIMER_SHORT,
        NO_FACE_MESSAGE,
    )

    # 상담 질문도 화면에 그대로 나간다 — 상수를 직접 읽는다.
    from app.services.virtual_surgery_simulator import (
        _QUESTION_IF_REFERRAL,
        _QUESTIONS_ALWAYS,
        _QUESTIONS_BY_CATEGORY,
    )

    questions = [*_QUESTIONS_ALWAYS, _QUESTION_IF_REFERRAL]
    for group in _QUESTIONS_BY_CATEGORY.values():
        questions.extend(group)

    return [DISCLAIMER_SHORT, DISCLAIMER_FULL, NO_FACE_MESSAGE, *questions] + _korean_literals(
        SIMULATOR, r'^\s*message = "([^"]+)"'
    ) + _korean_literals(SIMULATOR, r'"message":\s*"([^"]+)"') + _korean_literals(
        # 얼굴 미검출 이유 — diagnose_no_face 의 return 문들.
        SIMULATOR, r'^\s*return "([^"]+)"'
    )


@pytest.mark.parametrize("literal", _simulator_literals())
def test_simulator_strings_have_japanese(literal: str) -> None:
    assert literal in _i18n_text(), (
        f"i18n.ts 에 번역이 없습니다 — 일본어 모드에서 한국어가 그대로 나갑니다:\n  {literal}"
    )


def test_check_coverage_does_not_silently_shrink() -> None:
    """검사 대상이 줄어드는 것 자체를 잡는다.

    이 파일의 진짜 실패 모드는 '테스트가 깨지는 것'이 아니라 **'테스트가 조용히 대상을
    놓치는 것'** 이다. 실제로 한 번 일어났다. 하한을 두어 그때 빨간불이 뜨게 한다.
    문구를 정말 줄였다면 이 숫자를 같이 내리면 된다.
    """
    simulator = len(_simulator_literals())
    face_shape = len(_korean_literals(FACE_SHAPE, r'"(?:계란형|둥근형|긴형|각진형|하트형|마름모형)":\s*"([^"]+)"'))
    assert simulator >= 9, f"시뮬레이터 검사 대상이 {simulator}건으로 줄었습니다 — 정규식이 놓치고 있는지 확인하세요"
    assert face_shape >= 18, f"얼굴형 검사 대상이 {face_shape}건으로 줄었습니다"


@pytest.mark.parametrize("literal", _korean_literals(FACE_SHAPE, r'"(?:계란형|둥근형|긴형|각진형|하트형|마름모형)":\s*"([^"]+)"'))
def test_face_shape_texts_have_japanese(literal: str) -> None:
    """summaries·blusher_tips·shading_tips — **셋 다 화면에 그대로 나간다.**

    처음에는 tips 를 skip 으로 넘겼는데, App.tsx 를 확인해 보니 blusherTip/shadingTip 으로
    렌더링되고 있었다. skip 은 '검사 안 함'이지 '문제 없음'이 아니다.
    """
    assert literal in _i18n_text(), (
        f"i18n.ts 에 번역이 없습니다 — 일본어 모드에서 한국어가 그대로 나갑니다:\n  {literal}"
    )


def test_referral_message_is_translated_as_one_string() -> None:
    """referral 은 두 문장이 **이어붙어** 나가므로, 조각이 아니라 전체가 키여야 한다."""
    from app.services.dermatology_analyzer import SCREENING_NOTE

    source = SIMULATOR.read_text(encoding="utf-8")
    match = re.search(r'"message":\s*"(사진에서 진료가[^"]+)"\s*\+\s*SCREENING_NOTE', source)
    assert match, "referral 메시지 구성이 바뀌었습니다 — 이 테스트를 같이 고치세요"

    combined = match.group(1) + SCREENING_NOTE
    assert combined in _i18n_text(), (
        "이어붙인 전체 문자열이 i18n.ts 에 없습니다. 조각만 넣으면 매칭되지 않습니다:\n"
        f"  {combined}"
    )
