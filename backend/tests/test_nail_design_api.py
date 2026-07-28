"""POST /api/analyze-nail-design 계약 테스트.

모델·인덱스는 배포에 따라 있을 수도 없을 수도 있으므로, **없을 때 500 이 아니라
feature_available=False 로 떨어지는지**가 핵심이다(다른 AI 모듈과 같은 규약).
"""
from collections.abc import Generator
from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services import nail_design_index


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def _png_bytes(size: tuple[int, int] = (256, 256)) -> bytes:
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    buf = BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def test_rejects_non_image(client: TestClient) -> None:
    r = client.post(
        "/api/analyze-nail-design",
        files={"image": ("a.txt", b"not an image", "text/plain")},
    )
    assert r.status_code == 400


def test_reports_unavailable_instead_of_500(client: TestClient, monkeypatch) -> None:
    """모델·인덱스가 배포에 빠져도 200 + feature_available=False 여야 한다."""
    monkeypatch.setattr(nail_design_index, "feature_available", lambda: False)
    r = client.post(
        "/api/analyze-nail-design",
        files={"image": ("a.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["feature_available"] is False
    assert body["detected"] == []
    assert body["note"]


def test_no_nail_detected_returns_guidance(client: TestClient, monkeypatch) -> None:
    """네일이 안 잡히면 빈 결과 + 안내문. 에러가 아니다."""
    monkeypatch.setattr(nail_design_index, "feature_available", lambda: True)
    monkeypatch.setattr(nail_design_index, "detect_nails", lambda *a, **k: [])

    class _Idx:
        size = 123

        def load(self):
            return True

    monkeypatch.setattr(nail_design_index, "get_index", lambda: _Idx())
    r = client.post(
        "/api/analyze-nail-design",
        files={"image": ("a.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["feature_available"] is True
    assert body["index_size"] == 123
    assert body["detected"] == []
    assert "네일" in body["note"]


def test_returns_matches_and_season_fit(client: TestClient, monkeypatch) -> None:
    """검출이 되면 유사 디자인·시즌 적합도·검색어가 함께 나온다."""
    monkeypatch.setattr(nail_design_index, "feature_available", lambda: True)
    monkeypatch.setattr(
        nail_design_index, "detect_nails", lambda *a, **k: [((10, 10, 90, 110), 0.93)]
    )
    monkeypatch.setattr(
        nail_design_index, "dominant_color", lambda crop: ([30.0, 45.0, 10.0], "#6e1a2e")
    )

    class _Emb:
        def __call__(self, crops):
            return np.zeros((len(crops), 1280), dtype=np.float32)

    match = nail_design_index.DesignMatch(
        design_id="D19248_02_RGB_01", region="foot", similarity=0.82,
        color_hex="#d91a32", delta_e=4.2, thumbnail_path=None,
    )

    class _Idx:
        size = 6340

        def load(self):
            return True

        def search(self, *a, **k):
            return [match]

    monkeypatch.setattr(nail_design_index, "get_embedder", lambda: _Emb())
    monkeypatch.setattr(nail_design_index, "get_index", lambda: _Idx())

    r = client.post(
        "/api/analyze-nail-design",
        files={"image": ("a.png", _png_bytes(), "image/png")},
        data={"top_k": "5"},
    )
    assert r.status_code == 200
    body = r.json()

    assert body["feature_available"] is True
    assert len(body["detected"]) == 1
    nail = body["detected"][0]
    assert nail["confidence"] == 0.93
    assert nail["bbox"] == [10, 10, 90, 110]
    assert nail["matches"][0]["design_id"] == "D19248_02_RGB_01"

    # 7개 시즌 전부, 잘 맞는 순으로.
    assert len(body["season_fit"]) == 7
    scores = [s["delta_e"] for s in body["season_fit"]]
    assert scores == sorted(scores)

    # 검색어는 PROFILES 의 네일 색이름 그대로여야 item-match 에 넘길 수 있다.
    from app.services.personal_color_analyzer import PROFILES

    best = body["season_fit"][0]
    expected = PROFILES[(best["tone"], best["subtype"])].makeup.nail
    assert body["recommended_shades"] == expected


def test_deep_burgundy_maps_to_winter_deep(client: TestClient, monkeypatch) -> None:
    """진한 버건디는 겨울 쿨 딥이 1순위로 나와야 한다(브리지가 실제로 작동하는지)."""
    from app.services.nail_palette import hex_to_lab

    monkeypatch.setattr(nail_design_index, "feature_available", lambda: True)
    monkeypatch.setattr(
        nail_design_index, "detect_nails", lambda *a, **k: [((0, 0, 60, 80), 0.9)]
    )
    monkeypatch.setattr(
        nail_design_index, "dominant_color",
        lambda crop: ([round(v, 2) for v in hex_to_lab("#6E1A2E")], "#6e1a2e"),
    )

    class _Emb:
        def __call__(self, crops):
            return np.zeros((len(crops), 1280), dtype=np.float32)

    class _Idx:
        size = 10

        def load(self):
            return True

        def search(self, *a, **k):
            return []

    monkeypatch.setattr(nail_design_index, "get_embedder", lambda: _Emb())
    monkeypatch.setattr(nail_design_index, "get_index", lambda: _Idx())

    r = client.post(
        "/api/analyze-nail-design",
        files={"image": ("a.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["season_fit"][0]["label"] == "겨울 쿨 딥"
    assert body["season_fit"][0]["shade_name"] == "버건디"
