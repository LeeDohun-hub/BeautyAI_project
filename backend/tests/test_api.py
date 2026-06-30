from collections.abc import Generator
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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


def test_body_analysis_reports_model_state(client: TestClient) -> None:
    image = Image.new("RGB", (64, 64), (180, 130, 110))
    payload = BytesIO()
    image.save(payload, format="JPEG")
    response = client.post(
        "/api/analyze-skin",
        data={"analysis_mode": "body"},
        files={"image": ("body.jpg", payload.getvalue(), "image/jpeg")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["analysis_mode"] == "body"
    assert body["scores"] is None
    assert "model_available" in body


def test_body_recommendation_avoids_strong_actives(client: TestClient) -> None:
    response = client.post(
        "/api/recommend",
        json={
            "analysis_mode": "body",
            "body_conditions": [
                {
                    "condition": "atopic_dermatitis",
                    "label": "아토피 피부염",
                    "probability": 72,
                }
            ],
            "survey": {
                "skin_type": "sensitive",
                "concerns": ["아토피"],
                "sensitivity": 5,
                "routine_level": "basic",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    product_ingredients = {
        ingredient
        for product in body["products"]
        for ingredient in product["ingredients"]
    }
    assert not product_ingredients.intersection(
        {"Retinol", "Salicylic Acid", "Glycolic Acid", "Lactic Acid"}
    )
