"""점·잡티 — 자동 제거가 아니라 '후보 표시 + 사용자가 고른 것만 제거'.

왜 바꿨나(2026-08-04): 자동 제거는 오탐/미탐 줄다리기가 끝나지 않는다.
실측에서 후보 45개 중 대부분이 눈썹·쌍꺼풀선·입술선이었고, 이목구비를 빼도 13개가 남는데
그중에도 헤어라인이 섞였다. 정작 뚜렷한 주근깨는 못 잡았다.
후보만 보여주고 사용자가 고르면, **오탐이 나와도 안 고르면 그만**이라 정밀도 요구가 낮아진다.
"""

import numpy as np
import pytest

from app.services import virtual_surgery_simulator as vss


def _skin(size: int = 400) -> np.ndarray:
    rng = np.random.default_rng(0)
    return np.clip(rng.normal(180, 6, size=(size, size, 3)), 0, 255).astype(np.uint8)


def _with_spots(base: np.ndarray, spots: list[tuple[int, int, int]]) -> np.ndarray:
    import cv2

    out = base.copy()
    for x, y, r in spots:
        cv2.circle(out, (x, y), r, (110, 95, 90), -1)
    return out


def test_candidates_are_normalised_coordinates() -> None:
    """픽셀이 아니라 0~1 비율이어야 프론트가 어떤 크기로 그려도 맞는다."""
    rgb = _with_spots(_skin(), [(120, 150, 4), (250, 300, 5)])
    mask = np.ones(rgb.shape[:2], dtype=np.float32)
    for c in vss.find_blemish_candidates(rgb, mask):
        assert 0.0 <= c["x"] <= 1.0 and 0.0 <= c["y"] <= 1.0, c


def test_candidates_are_capped() -> None:
    """후보가 너무 많으면 화면에서 고를 수가 없다."""
    import cv2

    rgb = _skin(600)
    for i in range(80):
        cv2.circle(rgb, (20 + (i % 20) * 28, 20 + (i // 20) * 28), 4, (110, 95, 90), -1)
    mask = np.ones(rgb.shape[:2], dtype=np.float32)
    assert len(vss.find_blemish_candidates(rgb, mask)) <= 30


def test_finding_candidates_does_not_modify_the_photo() -> None:
    """탐지는 **지우지 않는다.** 이게 이번 변경의 핵심이다."""
    rgb = _with_spots(_skin(), [(120, 150, 4)])
    before = rgb.copy()
    vss.find_blemish_candidates(rgb, np.ones(rgb.shape[:2], dtype=np.float32))
    assert np.array_equal(rgb, before)


def test_removal_only_touches_chosen_points() -> None:
    rgb = _with_spots(_skin(), [(120, 150, 5), (300, 320, 5)])
    mask = np.ones(rgb.shape[:2], dtype=np.float32)
    # 첫 지점만 고른다.
    out = vss.remove_blemishes(rgb, [{"x": 120 / 400, "y": 150 / 400, "r": 5 / 400}])
    changed = np.abs(out.astype(int) - rgb.astype(int)).sum(axis=2) > 6
    assert changed[140:160, 110:130].any(), "고른 지점이 안 지워졌다"
    assert not changed[310:330, 290:310].any(), "안 고른 지점이 지워졌다"


@pytest.mark.parametrize("points", [[], None])
def test_removal_with_nothing_selected_is_a_noop(points) -> None:
    rgb = _skin()
    assert np.array_equal(vss.remove_blemishes(rgb, points or []), rgb)


def test_feature_regions_are_excluded_when_landmarks_given() -> None:
    """이목구비 제외가 실제로 후보를 줄이는지. 실측에서는 43 → 13 개였다."""

    class _LM:
        def __init__(self, x: float, y: float) -> None:
            self.x, self.y = x, y

    # 눈·눈썹·입술 인덱스가 모두 화면 중앙 부근을 가리키게 만든다.
    landmarks = [_LM(0.5, 0.5) for _ in range(500)]
    rgb = _with_spots(_skin(), [(200, 200, 5)])  # 중앙 = 제외 영역
    mask = np.ones(rgb.shape[:2], dtype=np.float32)
    without = vss.find_blemish_candidates(rgb, mask, None)
    with_lm = vss.find_blemish_candidates(rgb, mask, landmarks)
    assert len(with_lm) < len(without) or not with_lm
