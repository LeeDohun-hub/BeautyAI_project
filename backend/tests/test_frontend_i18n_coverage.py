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

# 한국어 원문을 그대로 넘기는 인자 — t() 로 감싸면 매칭되지 않는다.
RE_RAW_KOREAN_ARG = r"\(\s*'([^']*[가-힣][^']*)'"


def _app() -> str:
    return APP.read_text(encoding="utf-8")


def _i18n() -> str:
    return I18N.read_text(encoding="utf-8")


def _ui_sources() -> str:
    """화면을 그리는 모든 소스.

    ⚠ 예전에는 App.tsx 하나만 봤다. 그래서 화면 컴포넌트를 **새 파일로 분리하는 순간**
      이 검사가 조용히 눈을 감았다(AdminJourneyPanel.tsx 를 만들면서 드러났다).
      파일이 늘어나는 건 정상적인 리팩터링이므로 검사 쪽이 따라가야 한다.
    """
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(FRONTEND.rglob("*.tsx"))
    )


def _ui_korean() -> set[str]:
    """화면에 나가는 한국어 문자열을 모은다.

    · t('…')  직접 호출
    · label: '…'  드롭다운/버튼 옵션 정의(대부분 t(item.label) 로 나간다)
    """
    source = _ui_sources()
    found = set(re.findall(r"t\(\s*'([^']+)'\s*\)", source))
    found |= set(re.findall(r'\bt\(\s*"([^"]+)"\s*\)', source))
    found |= set(re.findall(r"label:\s*'([^']+)'", source))
    found |= set(re.findall(r"setError\(\s*t\(\s*'([^']+)'", source))
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


def test_error_messages_go_through_t() -> None:
    """오류·안내 문구가 t() 를 거치는지 본다 — set 할 때든 render 할 때든 한 번은 거쳐야 한다.

    ⚠ 이 부류가 가장 오래 숨어 있었다(2026-08-19 발견: setError 21곳 중 t() 통과 1곳).
      이유가 두 가지 겹쳤다.
        1. _ui_korean() 이 t('…') 와 label: '…' 만 훑어서 setError('…') 를 못 봤다.
        2. **오류는 정상 흐름에서 안 보인다.** 화면을 아무리 둘러봐도 드러나지 않고,
           한국어 사용자에게는 영원히 정상으로 보인다.
      실제로 6건은 번역이 사전에 **있는데도** t() 를 안 거쳐 한국어가 나갔다 —
      드롭다운(test_dropdown_options_go_through_t)과 완전히 같은 실수다.

    이 코드베이스에는 두 방식이 다 쓰인다. 어느 쪽이든 상관없지만 **둘 중 하나는** 해야 한다.
      · set 할 때 번역: setError(t('…'))          ← 사전 키가 코드에 남는다
      · render 할 때 번역: {t(authError)}          ← 상태에는 한국어 원문을 담아 둔다
    그래서 '원문을 그대로 set 하는' 곳을 찾고, 그 상태가 t() 로 렌더되는지까지 확인한다.
    myFaceError 가 정확히 이 틈으로 빠져나갔다 — set 도 render 도 t() 를 안 거쳤다.
    """
    source = _ui_sources()
    setter = re.compile(r"set([A-Za-z]*(?:Error|Failed|Notice|Message))" + RE_RAW_KOREAN_ARG)
    leaked: list[str] = []
    for name, text in setter.findall(source):
        state = name[0].lower() + name[1:]
        # 상태를 t() 로 렌더하고 있으면 통과 — 번역 시점만 다를 뿐 결과는 같다.
        if re.search(r"t\(\s*" + re.escape(state) + r"\s*\)", source):
            continue
        leaked.append(f"set{name}('{text}')")
    assert not leaked, (
        f"오류·안내 문구가 t() 를 거치지 않습니다 {len(leaked)}건 — "
        "일본어 모드에서 한국어가 나갑니다:" + "\n"
        + ("\n").join(f"  {s}" for s in sorted(set(leaked)))
    )


@pytest.mark.parametrize("marker", ["'윤곽·얼굴형'", "'코 라인'", "'자연스러운 변화'"])
def test_surgery_choice_options_are_translated(marker: str) -> None:
    """사용자가 1단계에서 고르는 항목. 여기가 한국어면 일본 사용자는 무엇을 고르는지 모른다."""
    assert marker in _i18n(), f"{marker} 번역이 없습니다"


# ── 백엔드가 만들어 내려주는 한국어 (2026-08-06 사용자 제보) ────────────────────
#
# 위 검사들은 **프론트 소스**의 한국어 리터럴만 훑는다. 그래서 서버가 런타임에 조립해
# 내려주는 문자열은 통째로 사각지대였다 — 일본몰 결과지에 추천 사유 배지와 컬럼 부제가
# 한국어로 나갔다(모공/피지, 유분 밸런스, `모공/피지 · 톤/색소 케어` …).
#
# 이 값들은 recommender 가 상수로 갖고 있어 열거할 수 있다. 열거 가능한 것은 검사한다.

RECOMMENDER = Path(__file__).resolve().parents[1] / "app" / "services" / "recommender.py"


def _backend_reason_tags() -> set[str]:
    """추천 사유 배지로 나가는 한국어 상수."""
    source = RECOMMENDER.read_text(encoding="utf-8")
    labels = re.search(r"REASON_TARGET_LABELS\s*=\s*\{(.*?)\}", source, re.S)
    assert labels, "REASON_TARGET_LABELS 를 찾지 못했습니다(이름이 바뀌었다면 이 검사도 고칠 것)"
    tags = set(re.findall(r"[\"']([^\"']*[가-힣][^\"']*)[\"']", labels.group(1)))
    # reason_tags.append("…") 로 직접 붙는 것들
    tags |= set(re.findall(r"reason_tags\.append\(\s*[\"']([^\"']+)[\"']", source))
    return {t for t in tags if HANGUL.search(t)}


def test_backend_reason_tags_have_japanese() -> None:
    i18n = _i18n()
    missing = sorted(
        tag for tag in _backend_reason_tags()
        if f"'{tag}'" not in i18n and f'"{tag}"' not in i18n
    )
    assert not missing, (
        f"백엔드가 내려주는 추천 사유 {len(missing)}건에 일본어가 없습니다 — "
        "일본몰 결과지에 한국어로 나갑니다:\n" + "\n".join(f"  {s}" for s in missing)
    )


def test_column_reason_is_translated_before_render() -> None:
    """컬럼 부제(col.reason)는 서버가 태그를 조립해 만든다.

    번역이 사전에 있어도 렌더가 t() 를 안 거치면 한국어가 그대로 나간다 —
    드롭다운(test_dropdown_options_go_through_t)과 같은 부류의 실수다.
    """
    assert "{col.reason ||" not in _app(), (
        "col.reason 을 번역 없이 그대로 렌더하고 있습니다 — tColumnReason() 을 거치게 하세요"
    )


# ── 가상성형: 서버가 만들어 내려주는 문자열 (2026-08-06 사용자 제보) ─────────────
#
# 4·5단계에 한국어가 섞여 나갔다 — 카드 제목/요약, 변화 설명, 흐름 단계명.
# 카드 제목·요약은 t() 를 거치는데 **사전이 없었고**, 변화 설명은 수치가 끼는 조립형이라
# 완성형을 사전에 넣을 수 없어 프론트가 자리표시자로 되돌려 옮긴다(tSurgeryDetail).

SURGERY = Path(__file__).resolve().parents[1] / "app" / "services" / "virtual_surgery_simulator.py"


def _surgery_card_strings() -> set[str]:
    """추천 카드의 title/summary — t() 로 그대로 나가는 값이다.

    ⚠ 값 뒤에 `",` 가 바로 오는 것만 본다. 조립형은 조각으로 검사하면 안 된다 —
      `"1단계에서 고른 " + " · ".join(...) + " 를 …"` 의 앞 조각은 런타임에 단독으로
      존재하지 않으므로 사전에 넣을 대상이 아니다(합쳐진 형태를 템플릿으로 옮긴다.
      아래 test_surgery_detail_templates_exist 가 그쪽을 지킨다).
    """
    source = SURGERY.read_text(encoding="utf-8")
    found: set[str] = set()
    for key in ("title", "summary"):
        found |= set(re.findall(rf'"{key}":\s*"([^"]*[가-힣][^"]*)",', source))
    return found


def test_surgery_card_strings_have_japanese() -> None:
    i18n = _i18n()
    missing = sorted(
        s for s in _surgery_card_strings()
        if f"'{s}'" not in i18n and f'"{s}"' not in i18n
    )
    assert not missing, (
        f"가상성형 카드 문자열 {len(missing)}건에 일본어가 없습니다:\n"
        + "\n".join(f"  {s[:70]}" for s in missing)
    )


@pytest.mark.parametrize(
    "template",
    [
        "'{where} 폭을 약 {n}% 정리했습니다.'",
        "'콧방울 폭을 약 {n}% 좁히고 콧대에 하이라이트를 얹었습니다.'",
        "'사진에서 자동 후보 {n}개를 찾았습니다.",
        "'턱끝 쪽에서'",
        "'중안부까지 넓게'",
        "'하관을 중심으로'",
        # 문자열 연결로 만들어지는 목표 요약(`"1단계에서 고른 " + … + " 를 …"`).
        "'1단계에서 고른 {targets} 를 반영한 미리보기입니다.'",
    ],
)
def test_surgery_detail_templates_exist(template: str) -> None:
    """수치가 끼는 문장은 자리표시자 템플릿으로 사전에 둔다."""
    assert template in _i18n(), f"{template} 템플릿이 없습니다 — 일본어 모드에서 한국어가 나갑니다"


def test_surgery_effect_detail_goes_through_translator() -> None:
    """effect.detail 을 그대로 렌더하면 사전이 있어도 한국어가 나간다."""
    app = _app()
    assert "{effect.detail}" not in app, (
        "effect.detail 을 번역 없이 렌더하고 있습니다 — tSurgeryDetail() 을 거치게 하세요"
    )


def test_flow_steps_all_translated() -> None:
    """가상성형 흐름 단계명. 하나만 빠져도 그 단계에서 한국어가 튄다(실제로 4단계가 그랬다)."""
    app = _app()
    match = re.search(r"const flowSteps = \[(.*?)\]", app, re.S)
    assert match, "flowSteps 를 찾지 못했습니다"
    steps = re.findall(r"'([^']+)'", match.group(1))
    i18n = _i18n()
    missing = [s for s in steps if HANGUL.search(s) and f"'{s}'" not in i18n]
    assert not missing, f"흐름 단계명에 번역이 없습니다: {missing}"
