from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_products_seeded(client: TestClient) -> None:
    response = client.get("/api/products")
    assert response.status_code == 200
    assert len(response.json()) >= 5


def test_recommend_with_scores(client: TestClient) -> None:
    response = client.post(
        "/api/recommend",
        json={
            "scores": {
                "acne": 60,
                "pore": 55,
                "wrinkle": 20,
                "redness": 45,
                "pigmentation": 30,
                "oiliness": 70,
            },
            "survey": {
                "skin_type": "oily",
                "concerns": ["acne", "pore"],
                "sensitivity": 3,
                "routine_level": "basic",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["products"]) == 5
    assert body["ingredients"]
