"""가상 성형 응답 직렬화 회귀 테스트(2026-07-30).

증상: 브라우저에서 가상 성형 분석이 CORS 오류로 실패. 실제 원인은 CORS 가 아니라
      `PydanticSerializationError: Unable to serialize unknown type: <class 'numpy.int64'>` —
      응답 metrics 의 face_box 가 numpy 정수였다. 에러 응답엔 CORS 헤더가 안 붙기 때문에
      브라우저 콘솔에는 CORS 문제로만 보여서 원인 파악이 늦었다.

⚠ numpy.float64 는 파이썬 float 의 하위 타입이라 통과하지만, numpy.int64 는 int 의 하위 타입이
  **아니다**. 그래서 정수 계열만 터진다 — 새 지표를 metrics 에 넣을 때 같은 함정에 빠지기 쉽다.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.virtual_surgery_simulator import _face_bounds


def test_face_bounds_returns_builtin_int():
    """numpy 배열에서 뽑은 좌표라도 파이썬 int 로 돌려줘야 응답에 실을 수 있다."""
    points = np.array([[10, 20], [200, 300], [50, 90]], dtype=np.int64)
    bounds = _face_bounds(points, w=640, h=480)

    assert len(bounds) == 4
    for value in bounds:
        assert type(value) is int, f"{value!r} 이 {type(value)} 다 — numpy 타입이면 직렬화가 터진다"


def test_face_bounds_clamps_to_image():
    points = np.array([[0, 0], [640, 480]], dtype=np.int64)
    x1, y1, x2, y2 = _face_bounds(points, w=640, h=480)
    assert (x1, y1) == (0, 0)
    assert x2 <= 640 and y2 <= 480


@pytest.mark.parametrize("dtype", [np.int32, np.int64])
def test_face_bounds_handles_int_dtypes(dtype):
    points = np.array([[5, 5], [100, 120]], dtype=dtype)
    assert all(type(v) is int for v in _face_bounds(points, w=200, h=200))


def test_metrics_payload_is_json_serializable():
    """metrics 에 들어가는 값들이 FastAPI 응답으로 나갈 수 있는지(=순수 파이썬 타입인지)."""
    import json

    points = np.array([[10, 20], [200, 300]], dtype=np.int64)
    x1, y1, x2, y2 = _face_bounds(points, w=640, h=480)
    payload = {"face_box": [x1, y1, x2, y2], "blemish_candidates": 3, "naturalness_score": 88}
    json.dumps(payload)  # numpy 타입이 섞여 있으면 TypeError 로 실패한다


# ── 1단계 선택값이 추천까지 오는지 (2026-08-03 사용자 지적) ─────────────────────
# "실제로 저거 선택한게 결과지까지 가야 하는데" — 그전엔 concern/desiredMood 가 프론트
# state 에만 있고 백엔드로 오지 않아, 무엇을 골라도 추천이 똑같았다.

def test_selected_concerns_reorder_recommendations_without_touching_scores():
    """고른 부위가 위로 오되 **점수는 그대로** 여야 한다.

    점수는 '사진에서 그렇게 보인다'는 측정값이다. 사용자가 골랐다고 점수를 올리면
    근거가 무너지고, 설계안이 금지한 '단정'에 가까워진다. 정렬과 표시만 바꾼다.
    """
    from app.services.virtual_surgery_simulator import _prioritize

    recs = [
        {"title": "윤곽", "category": "face_frame", "score": 86, "summary": ""},
        {"title": "입체감", "category": "nose_contour", "score": 72, "summary": ""},
        {"title": "잡티", "category": "blemish", "score": 64, "summary": ""},
    ]
    out = _prioritize([dict(r) for r in recs], ["코 라인", "점·잡티 제거"])

    assert [r["category"] for r in out] == ["nose_contour", "blemish", "face_frame"]
    assert [r["selected"] for r in out] == [True, True, False]
    # 점수는 원본 그대로
    by_cat = {r["category"]: r["score"] for r in out}
    assert by_cat == {"face_frame": 86, "nose_contour": 72, "blemish": 64}


def test_no_concerns_keeps_original_order():
    from app.services.virtual_surgery_simulator import _prioritize

    recs = [{"title": "a", "category": "face_frame", "score": 1, "summary": ""}]
    assert _prioritize([dict(r) for r in recs], None) == recs


def test_unknown_concern_is_ignored():
    """화면 문구를 그대로 키로 쓰므로, 사전에 없는 값이 와도 깨지지 않아야 한다."""
    from app.services.virtual_surgery_simulator import _prioritize

    recs = [
        {"title": "윤곽", "category": "face_frame", "score": 86, "summary": ""},
        {"title": "입체감", "category": "nose_contour", "score": 72, "summary": ""},
    ]
    out = _prioritize([dict(r) for r in recs], ["없는항목", "코 라인"])
    assert [r["category"] for r in out] == ["nose_contour", "face_frame"]
