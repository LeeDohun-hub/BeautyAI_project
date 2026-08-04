"""퍼스널컬러 조명 게이트.

사용자 제보: 어두운 곳(주점)에서 찍은 사진으로 분석했더니 결과가 자기 퍼스널컬러와 달랐다.
원인은 모델이 아니라 **답할 수 없는 사진에 답을 한 것**이다. WB(공막 기준 조명 보정)가
실패하면 픽셀 색상과 분광측색 실측의 상관이 0.09 로 사실상 무의미한데, 예전에는
색 가중치만 절반으로 낮추고 계절을 판정했다.

문턱 근거(2026-08-04 실측):
  AI-Hub 4조명 × 60장   5000lux → WB 100% / 500lux → WB 0%  (색온도와 무관, 조도로 갈림)
  실기기 폰 실내 12장    통과 75%, 밝기 0.495~0.592
  같은 사진 60% 밝기     통과 0%

여기서 지키는 것은 **양쪽**이다. 어두운 사진을 막는 것뿐 아니라, 평범한 실내 사진을
막지 않는 것. 게이트가 너무 빡빡하면 기능 자체를 못 쓴다.
"""

import pytest

from app.services.personal_color_analyzer import (
    UnusablePhotoError,
    unusable_reason,
    usable_for_color,
)


def _reading(**over) -> dict:
    """평범한 실내 폰 사진 수준(실측 밝기 0.495~0.592)."""
    base = {
        "white_balanced": True,
        "brightness": 0.52,
        "clipped": 0.0,
        "face_detected": True,
        "model_season_probs": None,
    }
    base.update(over)
    return base


def test_normal_indoor_photo_passes() -> None:
    """실기기 실내 사진이 막히면 기능을 못 쓴다."""
    assert usable_for_color(_reading())


@pytest.mark.parametrize("brightness", [0.590, 0.667, 0.824, 0.867])
def test_bright_studio_photo_passes(brightness: float) -> None:
    """AI-Hub 좋은 조명은 밝기가 0.867 까지 간다.

    기존 안내 문턱(상한 0.76)을 게이트로 썼으면 스튜디오 조명이 막혔다 — 상한을 안 두는 이유다.
    """
    assert usable_for_color(_reading(brightness=brightness))


def test_wb_failure_is_rejected() -> None:
    """이게 이번 변경의 핵심이다. 예전에는 통과시키고 가중치만 낮췄다."""
    assert not usable_for_color(_reading(white_balanced=False))


@pytest.mark.parametrize("brightness", [0.196, 0.261, 0.327, 0.37])
def test_dark_photo_is_rejected(brightness: float) -> None:
    """AI-Hub 500lux 실측 범위(0.196~0.327). 주점 조명이 이 구간이다."""
    assert not usable_for_color(_reading(brightness=brightness))


def test_blown_out_photo_is_rejected() -> None:
    """얼굴이 하얗게 날아가면 색 정보가 사라진다. 밝기 평균으로는 못 잡는다."""
    assert not usable_for_color(_reading(clipped=0.4))


def test_aihub_model_bypasses_the_gate() -> None:
    """AI-Hub 모델은 조명 보정을 내장하도록 학습됐다(그 문제를 풀려고 만든 모델).

    여기서 막으면 모델을 쓰는 의미가 없어진다 — WB 가 실패해도 통과시킨다.
    """
    assert usable_for_color(
        _reading(white_balanced=False, brightness=0.2, model_season_probs={"spring": 0.6})
    )


class TestReason:
    """이유 없이 막으면 사용자는 같은 사진을 다시 올린다."""

    def test_no_face(self) -> None:
        assert "얼굴" in unusable_reason([_reading(face_detected=False)])

    def test_dark(self) -> None:
        reason = unusable_reason([_reading(brightness=0.2), _reading(brightness=0.25)])
        assert "어두" in reason
        assert "창가" in reason, "무엇을 하면 되는지가 없으면 안내가 아니다"

    def test_color_cast(self) -> None:
        """밝기는 충분한데 WB 만 실패 = 색조명. 주점·무대 조명이 여기다."""
        reason = unusable_reason([_reading(white_balanced=False, brightness=0.55)])
        assert "조명" in reason
        assert "어두" not in reason, "밝은데 어둡다고 하면 사용자가 엉뚱한 걸 고친다"

    def test_empty(self) -> None:
        assert unusable_reason([])


def test_analyze_many_raises_when_nothing_usable() -> None:
    """한 장도 못 쓰면 판정하지 않는다 — 답을 내면 틀린 답이다."""
    from app.services.personal_color_analyzer import PersonalColorAnalyzer

    analyzer = PersonalColorAnalyzer()
    analyzer._read_one = lambda *a, **k: _reading(white_balanced=False, brightness=0.2)  # type: ignore[method-assign]
    with pytest.raises(UnusablePhotoError):
        analyzer.analyze_many([b"x", b"y"])
