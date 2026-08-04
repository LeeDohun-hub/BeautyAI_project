"""고른 점만 지우는 엔드포인트.

프론트가 좌표를 "x,y,r;x,y,r" 문자열로 보낸다. 형식이 어긋나면 조용히 아무것도 안 지우고
사용자는 '눌렀는데 안 지워진다'만 겪는다 — 파싱을 테스트로 붙잡는다.
"""

from collections.abc import Generator
from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def _photo_bytes() -> bytes:
    rng = np.random.default_rng(0)
    arr = np.clip(rng.normal(180, 6, size=(300, 300, 3)), 0, 255).astype(np.uint8)
    buf = BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _post(client: TestClient, points: str):
    return client.post(
        "/api/virtual-surgery/retouch",
        files={"image": ("face.jpg", _photo_bytes(), "image/jpeg")},
        data={"points": points},
    )


def test_removes_the_given_points(client: TestClient) -> None:
    res = _post(client, "0.4,0.5,0.02;0.6,0.3,0.02")
    assert res.status_code == 200
    body = res.json()
    assert body["removed"] == 2
    assert body["preview_image"].startswith("data:image/jpeg;base64,")


def test_empty_points_is_not_an_error(client: TestClient) -> None:
    """아무것도 안 고르고 눌러도 500 이 나면 안 된다."""
    res = _post(client, "")
    assert res.status_code == 200
    assert res.json()["removed"] == 0


@pytest.mark.parametrize("points", ["abc", "0.4", "0.4,;", ",,", "0.4,0.5,;x,y,z"])
def test_malformed_points_are_skipped_not_crashed(client: TestClient, points: str) -> None:
    """좌표가 깨져도 500 을 내지 않는다 — 형식이 바뀌면 조용히 0건이 되는 게 낫다."""
    res = _post(client, points)
    assert res.status_code == 200


def test_rejects_non_image(client: TestClient) -> None:
    res = client.post(
        "/api/virtual-surgery/retouch",
        files={"image": ("a.txt", b"not an image", "text/plain")},
        data={"points": "0.5,0.5,0.02"},
    )
    assert res.status_code == 400
