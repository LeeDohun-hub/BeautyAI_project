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


# ── 워프 상한 + 정면 게이트 (2026-08-03) ────────────────────────────────────────
# "비율조절 게이지바 실제로 바뀌지도 않는것 같음" — 상한이 7.5% 라 끝까지 밀어도 체감이
# 없었다. 12% 로 올리되, 축소가 얼굴 중심선 기준 대칭이라 각도가 있으면 한쪽만 눌린다.

def test_warp_cap_is_visible_but_not_identity_changing():
    """상한은 눈으로 확인해 정한 값이다. 임의로 되돌리거나 키우지 못하게 고정한다.

    같은 사진 실측: 7.5% 는 차이를 못 느끼고, 18% 는 원본에 없던 갸름함이 생겨
    시뮬레이터 주석이 경계로 삼은 identity-changing 영역으로 넘어간다.
    """
    from app.services.virtual_surgery_simulator import _MAX_FACE_NARROWING

    assert 0.10 <= _MAX_FACE_NARROWING <= 0.14


def test_frontal_gate_scales_warp_down_as_face_turns():
    from app.services.virtual_surgery_simulator import (
        _FRONTAL_FULL, _FRONTAL_NONE, _frontal_factor,
    )

    assert _frontal_factor(0.0) == 1.0                      # 정면 → 그대로
    assert _frontal_factor(_FRONTAL_FULL) == 1.0            # 경계까지는 그대로
    assert _frontal_factor(_FRONTAL_NONE) == 0.0            # 많이 돌면 워프 안 함
    assert _frontal_factor(_FRONTAL_NONE + 1.0) == 0.0      # 그 너머도 0
    mid = _frontal_factor((_FRONTAL_FULL + _FRONTAL_NONE) / 2)
    assert 0.0 < mid < 1.0                                  # 사이는 연속적으로 감소


def test_concern_maps_to_both_nose_and_balance():
    """`_recommendations` 는 nose_contour 와 balance 중 **하나만** 만든다(eye_ratio 분기).

    '코 라인'을 한쪽에만 걸면, 그 사진이 반대쪽으로 판정될 때 고른 게 통째로 무시된다
    (실측: 코를 골랐는데 잡티 추천이 맨 위로 왔다).
    """
    from app.services.virtual_surgery_simulator import _prioritize

    for category in ("nose_contour", "balance"):
        recs = [
            {"title": "잡티", "category": "blemish", "score": 64, "summary": ""},
            {"title": "코", "category": category, "score": 72, "summary": ""},
        ]
        out = _prioritize([dict(r) for r in recs], ["코 라인"])
        assert out[0]["category"] == category, f"{category} 가 맨 위여야 한다"
        assert out[0]["selected"] is True


def test_face_line_and_jaw_balance_are_independent():
    """두 값이 **합산**되던 시절엔 슬라이더가 2개인데 자유도가 1개였다.

    그 탓에 합이 같은 프리셋은 결과가 완전히 같았다(실측: '부드러운 동안형' vs '입체
    세련형' 픽셀차 0.02 — 카드가 달라도 그림이 같았다). face_line=양, jaw_balance=위치로
    분리했으니, **합이 같아도 결과가 달라야** 한다.
    """
    import numpy as np

    from app.services.virtual_surgery_simulator import _reshape_face

    rgb = np.random.default_rng(0).integers(0, 255, (200, 200, 3), dtype=np.uint8)
    pts = np.array([[60, 40], [140, 40], [150, 120], [100, 180], [50, 120]], dtype=np.int32)
    mask = np.ones((200, 200), dtype=np.float32)

    # 합이 같은 두 조합(0.3+0.7 vs 0.7+0.3)이 서로 다른 그림을 내야 한다.
    a = _reshape_face(rgb, mask, pts, 0.3, 0.7)
    b = _reshape_face(rgb, mask, pts, 0.7, 0.3)
    assert np.abs(a.astype(int) - b.astype(int)).mean() > 1.0


def test_card_presets_are_distinct():
    """카드 프리셋이 서로 충분히 달라야 미리보기가 구분된다.

    ⚠ 예전엔 (face_line, jaw_balance) 두 축만 봤다. 그래서 **코 중심 카드**를 막았다 —
      'defined'(코 라인 정리)는 얼굴선을 oval 과 비슷하게 두고 코만 크게 좁히는 카드인데
      (nose_contour 28 → 95, 네 축 중 가장 큰 차이), 얼굴선이 겹친다는 이유로 실패했다.
      실제로 미리보기는 코에서 확연히 갈린다.

    지키려는 건 '두 카드가 같아 보이면 안 된다'이지 '얼굴선이 달라야 한다'가 아니다.
    판정 방식(10 단위 버킷)은 그대로 두고 보는 축만 넓힌다 — 단일 축 임계값으로 바꿨더니
    oval↔soft(축별 최대 차 17)처럼 두 축이 함께 조금씩 움직여 구분되는 조합이 걸렸다.
    """
    from app.services.virtual_surgery_simulator import CARD_PRESETS

    axes = ("face_line", "jaw_balance", "nose_contour", "blemish_care")
    seen: dict[tuple[int, ...], str] = {}
    for preset in CARD_PRESETS:
        key = tuple(preset["tuning"][a] // 10 for a in axes)
        assert key not in seen, (
            f"{preset['id']} 의 프리셋이 {seen[key]} 와 겹친다 — 미리보기가 같아 보인다"
        )
        seen[key] = preset["id"]


# ── 질환 선별 게이트 (설계 검토 §4, 2026-08-03) ────────────────────────────────
# derma_tier1_gate.pt 는 바디 분석에만 쓰이고 성형 플로우엔 연결돼 있지 않았다.
# 미용 목적 사진이라도 진료가 필요한 소견이 보이면 그쪽을 먼저 알려야 한다.

def test_referral_is_empty_when_model_unavailable(monkeypatch):
    """선별 모델이 배포에 없어도 성형 기능 자체는 계속 돌아야 한다."""
    import app.services.virtual_surgery_simulator as vs

    class _Analyzer:
        @staticmethod
        def analyze(_):
            return {"model_available": False, "urgent": False}

    monkeypatch.setattr("app.services.dermatology_analyzer.DermatologyAnalyzer", _Analyzer)
    out = vs._screen_for_referral(b"x")
    assert out["urgent"] is False and out["message"] == ""


def test_referral_survives_analyzer_crash(monkeypatch):
    """선별이 터져도 미용 추천을 막지 않는다(안내는 보조 정보다)."""
    import app.services.virtual_surgery_simulator as vs

    class _Boom:
        @staticmethod
        def analyze(_):
            raise RuntimeError("model blew up")

    monkeypatch.setattr("app.services.dermatology_analyzer.DermatologyAnalyzer", _Boom)
    assert vs._screen_for_referral(b"x")["urgent"] is False


def test_referral_reports_urgent_finding(monkeypatch):
    import app.services.virtual_surgery_simulator as vs

    class _Analyzer:
        @staticmethod
        def analyze(_):
            return {
                "model_available": True, "urgent": True,
                "tier1_label": "urgent_referral", "tier1_confidence": 91.2,
            }

    monkeypatch.setattr("app.services.dermatology_analyzer.DermatologyAnalyzer", _Analyzer)
    out = vs._screen_for_referral(b"x")
    assert out["urgent"] is True
    assert out["confidence"] == 91.2
    # 진단이 아니라 선별임을 문구가 말해야 한다.
    assert "진단이 아니라" in out["message"]
    assert "전문의" in out["message"]
