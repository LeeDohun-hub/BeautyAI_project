"""사진 품질 게이트.

문턱은 2026-08-04 실측으로 잡았다(docs/ 실사진 + 인위적 열화본 대조):

    지표                     정상 사진       열화본        문턱
    흐림(라플라시안 분산)    145~338        2.0          < 40
    밝기(얼굴 평균)          133~138        40           < 70
    과노출(>248 픽셀 비율)   0.000          0.767        > 0.15
    가림(피부중앙값 이탈)    0.086~0.150    0.373~0.651  > 0.28
    해상도(얼굴 폭 px)       678~836        —            < 250

여기서 지키려는 것은 **양쪽**이다. 열화본을 잡는 것뿐 아니라, 정상 사진이 걸리지 않는 것.
경고가 늘 뜨면 사용자는 경고를 읽지 않게 되고, 게이트는 없는 것과 같아진다.
"""

import numpy as np
import pytest

from app.services import virtual_surgery_simulator as vss

# 얼굴 오벌 대신 단순 사각형 폴리곤을 쓴다 — 게이트가 보는 것은 '영역 안의 픽셀 통계'라
# 랜드마크 모양 자체는 무관하고, Face Mesh 없이 결정적으로 테스트할 수 있다.
FACE = np.array([[100, 100], [500, 100], [500, 600], [100, 600]], dtype=np.float32)


def _photo(brightness: int = 135, noise: int = 26, size: tuple[int, int] = (700, 700)) -> np.ndarray:
    """초점이 맞은 보통 밝기의 사진. 노이즈가 고주파를 만들어 blur 지표를 정상 범위로 만든다."""
    rng = np.random.default_rng(0)
    base = rng.normal(brightness, noise, size=(*size, 3))
    return np.clip(base, 0, 255).astype(np.uint8)


def test_normal_photo_passes() -> None:
    result = vss.assess_photo_quality(_photo(), FACE)
    assert result["ok"], f"정상 사진이 걸리면 안 된다: {result['issues']}"
    assert result["issues"] == []


def _codes(rgb: np.ndarray, pts: np.ndarray = FACE) -> set[str]:
    return {issue["code"] for issue in vss.assess_photo_quality(rgb, pts)["issues"]}


def test_dark_photo_is_flagged() -> None:
    assert "dark" in _codes(_photo(brightness=40))


def test_overexposed_photo_is_flagged() -> None:
    # 대부분의 픽셀이 흰색으로 날아간 상태.
    blown = _photo(brightness=252, noise=2)
    assert "overexposed" in _codes(blown)


def test_blurry_photo_is_flagged() -> None:
    # 노이즈가 없는 매끈한 그라데이션 = 고주파 없음 = 초점 안 맞음과 같은 신호.
    y = np.linspace(90, 170, 700, dtype=np.float32)
    smooth = np.repeat(np.repeat(y[:, None], 700, axis=1)[:, :, None], 3, axis=2)
    assert "blurry" in _codes(smooth.astype(np.uint8))


def test_small_face_is_flagged() -> None:
    small = np.array([[10, 10], [180, 10], [180, 260], [10, 260]], dtype=np.float32)
    assert "small_face" in _codes(_photo(size=(300, 300)), small)


def test_occlusion_is_flagged() -> None:
    rgb = _photo()
    # 얼굴 영역의 절반을 어두운 덩어리로 덮는다(손·마스크·선글라스 상황).
    rgb[100:350, 100:500] = (35, 35, 40)
    assert "occluded" in _codes(rgb)


def test_gate_never_blocks() -> None:
    """품질이 나빠도 ok=False 일 뿐, 예외를 던지거나 결과를 비우지 않는다."""
    result = vss.assess_photo_quality(_photo(brightness=20), FACE)
    assert result["ok"] is False
    assert result["metrics"], "무엇 때문에 걸렸는지 알 수 있도록 수치도 함께 준다"


@pytest.mark.parametrize("pts", [np.array([[0, 0], [2, 0], [2, 2], [0, 2]], dtype=np.float32)])
def test_degenerate_region_does_not_crash(pts: np.ndarray) -> None:
    """얼굴 영역이 극단적으로 작아도 죽지 않는다(크롭이 비면 통계가 없다)."""
    result = vss.assess_photo_quality(_photo(), pts)
    assert result["ok"] is True
