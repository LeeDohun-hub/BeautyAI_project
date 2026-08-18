"""바디 '케어를 이어갔을 때' 시뮬레이션 — 색소가 실제로 지워지는지.

제보(2026-08-18): 바디 결과지의 After 가 원본과 구분되지 않았다. "어디가 나아진 건가요."

원인은 두 겹이었다.
  ① 색소 제거가 `face_mask is not None` 조건에 묶여 **바디에서는 실행 자체가 안 됐다.**
     바디는 홍조·결만 손대니, 눈에 띄는 건 그대로고 사진만 살짝 뿌예졌다.
  ② 고쳐서 실행시켜도 강도가 0.85 라 원본이 15% 비쳐 보였다(실측 원본 67 → 170,
     깨끗한 피부 187). 그 정도면 '지웠다'가 아니라 '문질렀다'로 보인다.

여기서 지키는 것:
  · 뚜렷한 색소는 주변 피부와 구분되지 않을 만큼 지워진다.
  · 깨끗한 피부는 건드리지 않는다(오탐으로 멀쩡한 피부를 뭉개면 더 나쁘다).
  · 검출이 병변 크기에 휘둘리지 않는다 — 이게 원래 못 잡던 이유였다.
"""

from __future__ import annotations

import base64

import cv2
import numpy as np
import pytest

from app.services.skincare_simulator import (
    _body_skin_mask,
    find_body_pigment_candidates,
    simulate_skincare,
)

SKIN_RGB = (222, 184, 160)
LESION_RGB = (92, 62, 48)


def _skin_photo(size: int = 420, seed: int = 7) -> np.ndarray:
    """살색 + 결(노이즈). 실제 사진처럼 완전히 평평하지는 않게 만든다."""
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size, 3), np.uint8)
    img[:, :] = SKIN_RGB
    img = np.clip(img + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8)
    return cv2.GaussianBlur(img, (5, 5), 0)


def _with_lesion(img: np.ndarray, center: tuple[int, int], radius: int) -> np.ndarray:
    out = img.copy()
    cv2.circle(out, center, radius, LESION_RGB, -1)
    return cv2.GaussianBlur(out, (5, 5), 0)


def _encode(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    assert ok
    return buf.tobytes()


def _decode(data_url: str) -> np.ndarray:
    raw = base64.b64decode(data_url.split(",", 1)[1])
    arr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    return cv2.cvtColor(arr, cv2.COLOR_BGR2RGB).astype(np.float32)


def _patch_gap(img: np.ndarray, center: tuple[int, int], radius: int) -> float:
    """병변 자리와 깨끗한 피부의 밝기 차이. 0 에 가까울수록 지워진 것이다."""
    x, y = center
    patch = img[y - radius: y + radius, x - radius: x + radius].mean()
    clean = img[40:90, 40:90].mean()
    return float(clean - patch)


def test_visible_pigment_is_actually_removed() -> None:
    photo = _with_lesion(_skin_photo(), (210, 200), 25)
    before_gap = _patch_gap(photo.astype(np.float32), (210, 200), 25)
    assert before_gap > 80, "테스트 사진의 색소가 충분히 뚜렷해야 한다"

    result = simulate_skincare(_encode(photo), {}, strength=1.0, mode="body")

    assert result["applied"] is True
    assert "pigmentation" in result["changed"], "바디에서 색소 제거가 실행되어야 한다"
    after_gap = _patch_gap(_decode(result["after"]), (210, 200), 25)
    # 5 는 사진 노이즈 수준이다. 이보다 남으면 화면에서 자국으로 보인다.
    assert abs(after_gap) < 5, f"색소가 남아 있다(차이 {after_gap:.1f})"


def test_clean_skin_is_left_alone() -> None:
    """오탐 방지. 멀쩡한 피부를 인페인팅으로 뭉개면 안 지운 것보다 나쁘다."""
    assert find_body_pigment_candidates(_skin_photo(), _body_skin_mask(_skin_photo())) == []


@pytest.mark.parametrize("radius", [8, 16, 25, 40])
def test_detection_does_not_depend_on_lesion_size(radius: int) -> None:
    """예전 방식(가우시안 국소평균)이 못 잡던 지점.

    커널이 병변보다 크지 않으면 '주변 평균'이 병변 자신에 끌려가 차이가 0 이 된다.
    실측(420px 사진, 지름 50px 병변): 커널 51px 에서 delta 0.7 → 검출 0건.
    바디는 접사라 병변이 크고 크기를 미리 알 수 없으므로 크기에 휘둘리면 안 된다.
    """
    photo = _with_lesion(_skin_photo(), (210, 200), radius)
    found = find_body_pigment_candidates(photo, _body_skin_mask(photo))

    assert found, f"반지름 {radius}px 병변을 찾지 못했다"
    nearest = min(found, key=lambda p: abs(p["x"] - 210 / 420) + abs(p["y"] - 200 / 420))
    assert abs(nearest["x"] * 420 - 210) < 12
    assert abs(nearest["y"] * 420 - 200) < 12
    # 지우는 반지름은 병변보다 넉넉해야 한다 — 딱 맞으면 가장자리 색이 남는다.
    assert nearest["r"] * 420 >= radius


def test_face_mode_is_unchanged_by_the_body_path() -> None:
    """바디 경로를 넣으면서 얼굴 경로를 건드리지 않았는지 확인.

    얼굴 사진이 아니면 랜드마크가 없어 applied=False 로 돌아와야 한다 — 원본을
    '개선 결과'라고 내보내는 것이 제일 나쁘다.
    """
    result = simulate_skincare(_encode(_skin_photo()), {"pigmentation": 70.0}, mode="face")

    assert result["applied"] is False
    assert result["after"] is None
    assert "얼굴" in result["message"]
