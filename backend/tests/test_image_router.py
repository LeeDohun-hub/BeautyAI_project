"""얼굴/바디 자동 판별(SkinImageRouter).

프론트 기본값을 'face' 고정에서 'auto' 로 바꾸면서(2026-08-18) 이 판정이 사용자가
아무것도 안 눌러도 타는 길이 됐다. 그전까지 테스트가 하나도 없었다.

문턱값을 왜 0.008 로 낮췄는지는 image_router.FACE_RATIO_THRESHOLD 주석 참조.
요약: 실측 얼굴 28장 중 4장이 바디로 샜고 3장이 문턱 바로 아래(0.009~0.022)였다.
0.008 로 내리면 얼굴 27/28, 바디는 239/240 그대로다.

여기서 지키는 것:
  · 얼굴이 없으면 바디로 간다(바디 사진이 얼굴 회귀기에 들어가면 점수를 지어낸다).
  · 문턱이 조용히 되돌아가지 않는다 — 되돌아가면 작게 찍힌 얼굴이 다시 바디로 샌다.
  · 판정 근거(비율·개수)를 응답에 남긴다. 왜 그렇게 갈렸는지 못 보면 고칠 수도 없다.
"""

from __future__ import annotations

from io import BytesIO

import cv2
import numpy as np
import pytest
from PIL import Image

from app.services.image_router import FACE_RATIO_THRESHOLD, SkinImageRouter


def _png(rgb: np.ndarray) -> bytes:
    buffer = BytesIO()
    Image.fromarray(rgb).save(buffer, format="PNG")
    return buffer.getvalue()


def _skin_patch(size: int = 420, seed: int = 5) -> np.ndarray:
    """얼굴이 없는 살색 사진(바디 접사에 해당)."""
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size, 3), np.uint8)
    img[:, :] = (222, 184, 160)
    img = np.clip(img + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8)
    return cv2.GaussianBlur(img, (5, 5), 0)


@pytest.fixture(scope="module")
def router() -> SkinImageRouter:
    return SkinImageRouter()


def test_a_photo_without_a_face_goes_to_body(router: SkinImageRouter) -> None:
    """가장 중요한 갈래. 여길 얼굴로 보내면 얼굴 회귀기가 바디 사진에 점수를 지어낸다."""
    route = router.route(_png(_skin_patch()))

    assert route.analysis_mode == "body"
    assert route.face_count == 0


def test_a_pigmented_body_closeup_still_goes_to_body(router: SkinImageRouter) -> None:
    """점이 있는 바디 접사 — 사용자가 실제로 올리는 사진 모양."""
    img = _skin_patch()
    cv2.circle(img, (210, 200), 25, (92, 62, 48), -1)

    assert router.route(_png(cv2.GaussianBlur(img, (5, 5), 0))).analysis_mode == "body"


def test_threshold_stays_low_enough_for_small_faces() -> None:
    """실측으로 정한 값이라 조용히 되돌아가면 안 된다.

    0.025 로 돌아가면 얼굴 비율 0.009~0.022 인 사진(정면이지만 얼굴이 작게 찍힌 것)이
    다시 바디로 새어, 6항목 점수 대신 질환 선별 결과를 받는다.
    """
    assert FACE_RATIO_THRESHOLD <= 0.010, "실측 근거 없이 문턱을 올리지 말 것"
    assert FACE_RATIO_THRESHOLD > 0, "0 이면 얼굴이 한 픽셀만 잡혀도 얼굴 사진이 된다"


def test_route_reports_why_it_decided(router: SkinImageRouter) -> None:
    route = router.route(_png(_skin_patch()))

    assert route.reason, "판정 근거 문구가 있어야 화면에서 이유를 안내할 수 있다"
    assert route.largest_face_ratio == 0.0
