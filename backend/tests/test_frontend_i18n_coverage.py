"""화면에 나가는 한국어가 전부 일본어 번역을 갖고 있는지 검사한다.

이 부류는 **오늘만 세 번 재발했다**:
  1. 법적 고지·의료 안내가 t() 없이 출력돼 일본 사용자에게 한국어로 나갔다
  2. 얼굴형 팁 12건을 skip 으로 넘겼는데 실제로는 화면에 렌더링되고 있었다
  3. 인종정체성 드롭다운이 t() 를 안 거쳐 한국어로 나왔다(사용자 제보)

공통점은 **화면은 멀쩡해 보이고 테스트도 통과한다**는 것이다. 한국어 사용자에게는
아무 문제가 없어서 드러나지 않는다. 사람이 매번 확인할 수 없으므로 여기서 잡는다.

⚠ 백엔드 테스트에 프론트 검사가 있는 것이 어색하지만, 프론트에는 테스트 러너가 없다.
   러너가 생기면 그쪽으로 옮기는 게 맞다.
"""

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
APP = FRONTEND / "App.tsx"
I18N = FRONTEND / "i18n.ts"

HANGUL = re.compile(r"[가-힣]")


def _app() -> str:
    return APP.read_text(encoding="utf-8")


def _i18n() -> str:
    return I18N.read_text(encoding="utf-8")


def _ui_korean() -> set[str]:
    """화면에 나가는 한국어 문자열을 모은다.

    · t('…')  직접 호출
    · label: '…'  드롭다운/버튼 옵션 정의(대부분 t(item.label) 로 나간다)
    """
    source = _app()
    found = set(re.findall(r"t\(\s*'([^']+)'\s*\)", source))
    found |= set(re.findall(r'\bt\(\s*"([^"]+)"\s*\)', source))
    found |= set(re.findall(r"label:\s*'([^']+)'", source))
    return {s for s in found if HANGUL.search(s)}


def test_every_ui_string_has_japanese() -> None:
    i18n = _i18n()
    missing = sorted(s for s in _ui_korean() if f"'{s}'" not in i18n and f'"{s}"' not in i18n)
    assert not missing, (
        f"i18n.ts 에 번역이 없는 화면 문자열 {len(missing)}건 — 일본어 모드에서 한국어가 나갑니다:\n"
        + "\n".join(f"  {s}" for s in missing)
    )


def test_dropdown_options_go_through_t() -> None:
    """MenuItem 이 값을 그대로 출력하면 번역이 있어도 한국어가 나간다.

    실제로 인종정체성 드롭다운이 그랬다 — i18n 에 번역이 **있었는데도** 한국어였다.
    번역 유무만 검사하면 이 부류를 못 잡는다.
    """
    raw = re.findall(r"<MenuItem[^>]*>\{([a-zA-Z][A-Za-z0-9_.]*)\}</MenuItem>", _app())
    assert not raw, (
        "MenuItem 이 t() 없이 값을 그대로 출력합니다 — 일본어 모드에서 한국어가 나갑니다: "
        f"{sorted(set(raw))}"
    )


@pytest.mark.parametrize("marker", ["'윤곽·얼굴형'", "'코 라인'", "'자연스러운 변화'"])
def test_surgery_choice_options_are_translated(marker: str) -> None:
    """사용자가 1단계에서 고르는 항목. 여기가 한국어면 일본 사용자는 무엇을 고르는지 모른다."""
    assert marker in _i18n(), f"{marker} 번역이 없습니다"
