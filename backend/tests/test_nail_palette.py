import pytest

from app.services.nail_palette import (
    NAIL_SHADE_HEX,
    delta_e76,
    hex_to_lab,
    nail_color_fit,
    rank_seasons,
    rgb_to_lab,
    season_nail_shades,
)
from app.services.personal_color_analyzer import PROFILES


def test_every_profile_nail_name_has_hex() -> None:
    """PROFILES 에 색이름이 추가되면 여기서 먼저 깨져서 알려준다."""
    missing = {
        name
        for profile in PROFILES.values()
        for name in profile.makeup.nail
        if name not in NAIL_SHADE_HEX
    }
    assert not missing, f"NAIL_SHADE_HEX 누락: {missing}"


def test_season_nail_shades_covers_every_profile() -> None:
    for tone, subtype in PROFILES:
        shades = season_nail_shades(tone, subtype)
        assert len(shades) == len(PROFILES[(tone, subtype)].makeup.nail)
        assert all(h.startswith("#") and len(h) == 7 for _, h in shades)


@pytest.mark.parametrize(
    ("rgb", "expected"),
    [
        ((255, 255, 255), (100.0, 0.0, 0.0)),
        ((0, 0, 0), (0.0, 0.0, 0.0)),
    ],
)
def test_rgb_to_lab_reference_points(rgb, expected) -> None:
    lab = rgb_to_lab(rgb)
    for got, want in zip(lab, expected):
        assert abs(got - want) < 0.5


def test_delta_e_is_zero_for_identical_color() -> None:
    lab = hex_to_lab("#C46B4E")
    assert delta_e76(lab, lab) == 0.0


def test_exact_shade_scores_full_marks() -> None:
    """팔레트 색 그대로면 ΔE 0 · 100점이어야 한다."""
    match = nail_color_fit(hex_to_lab("#C46B4E"), "warm", "deep")  # 테라코타
    assert match.name == "테라코타"
    assert match.delta_e == 0.0
    assert match.score == 100.0


def test_warm_coral_prefers_warm_season_over_cool() -> None:
    """웜 코랄은 쿨 시즌보다 웜 시즌에 더 가깝게 나와야 한다."""
    lab = hex_to_lab("#FF7F5F")
    warm = nail_color_fit(lab, "warm", "light")
    cool = nail_color_fit(lab, "cool", "light")
    assert warm.delta_e < cool.delta_e


def test_cool_pink_prefers_cool_season() -> None:
    lab = hex_to_lab("#E8A0B4")
    cool = nail_color_fit(lab, "cool", "light")
    warm = nail_color_fit(lab, "warm", "deep")
    assert cool.delta_e < warm.delta_e


def test_rank_seasons_is_sorted_and_complete() -> None:
    rows = rank_seasons(hex_to_lab("#6E1A2E"))  # 버건디
    assert len(rows) == len(PROFILES)
    deltas = [r[3].delta_e for r in rows]
    assert deltas == sorted(deltas)
    assert rows[0][0] == "겨울 쿨 딥"


def test_unknown_shade_name_raises() -> None:
    """이름만 추가하고 hex 를 안 채우면 조용히 넘어가지 않고 터져야 한다."""
    profile = PROFILES[("warm", "light")]
    original = profile.makeup.nail
    object.__setattr__(profile.makeup, "nail", [*original, "존재하지않는색"])
    try:
        with pytest.raises(KeyError, match="존재하지않는색"):
            season_nail_shades("warm", "light")
    finally:
        object.__setattr__(profile.makeup, "nail", original)


def test_score_drops_to_zero_for_far_color() -> None:
    """완전히 다른 색이면 0점으로 내려간다(음수로 안 감)."""
    match = nail_color_fit(hex_to_lab("#00FF00"), "cool", "deep")
    assert match.score == 0.0
