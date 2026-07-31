"""결과지 QR → 웹 장바구니 핸드오프.

여기서 지키는 것:
  - 코드는 1회용이고 짧게 산다(QR 은 브라우저 히스토리·출력물에 남는다).
  - 사용자 세션 토큰으로는 resolve 를 못 연다(서명 키가 같아서 subject 로만 갈린다).
  - 웹 계정과 연결 안 된 세션은 담을 장바구니가 없으므로 코드를 안 만든다.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import SERVICE_SUBJECT, SESSION_SUBJECT, TICKET_SUBJECT
from app.main import app


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def secret() -> str:
    return get_settings().jwt_secret


def ticket(secret: str, member_id: int) -> str:
    return jwt.encode(
        {
            "sub": TICKET_SUBJECT,
            "memberId": member_id,
            "jti": str(uuid.uuid4()),
            "name": "카트테스터",
            "loginId": "cart-tester",
            "role": "USER",
            "exp": datetime.now(timezone.utc) + timedelta(seconds=120),
        },
        secret,
        algorithm="HS256",
    )


def service_token(secret: str, *, subject: str = SERVICE_SUBJECT, expires_in: int = 60) -> str:
    return jwt.encode(
        {"sub": subject, "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_in)},
        secret,
        algorithm="HS256",
    )


def link(client: TestClient, secret: str, member_id: int) -> dict[str, str]:
    token = client.post("/api/auth/exchange", json={"ticket": ticket(secret, member_id)}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


ITEMS = [
    {
        "name": "아누아 어성초 토너",
        "brand": "Anua",
        "url": "https://www.amazon.com/dp/B08575Y9V3",
        "external_id": "B08575Y9V3",
    },
    {
        "name": "롬앤 쥬시 래스팅 틴트",
        "brand": "rom&nd",
        "url": "https://global.oliveyoung.com/product/detail?prdtNo=GA260237624",
        "external_id": "GA260237624",
    },
]


def test_handoff_round_trip(client: TestClient, secret: str) -> None:
    headers = link(client, secret, 7101)

    created = client.post("/api/cart/handoff", headers=headers, json={"items": ITEMS})
    assert created.status_code == 200
    body = created.json()
    assert body["item_count"] == 2
    # QR 이 이 주소를 담는다 — 코드만 실려야 짧게 유지된다.
    assert body["url"].endswith(f"ai={body['code']}")
    assert body["expires_in"] > 0

    resolved = client.post(
        "/internal/cart-handoff/resolve",
        headers={"Authorization": f"Bearer {service_token(secret)}"},
        json={"code": body["code"]},
    )
    assert resolved.status_code == 200
    payload = resolved.json()
    assert payload["web_member_id"] == 7101
    assert [item["url"] for item in payload["items"]] == [item["url"] for item in ITEMS]


def test_qr_url_stays_short(client: TestClient, secret: str) -> None:
    """QR 에 상품을 통째로 싣던 방식으로 되돌아가지 않게 길이를 못 박는다.

    상품 5개를 base64 로 실으면 1KB 를 넘겨 QR 이 아주 조밀해지고 출력물에서 인식이 어렵다.
    """
    headers = link(client, secret, 7102)
    many = [dict(ITEMS[0], name=f"상품 {index}") for index in range(5)]

    body = client.post("/api/cart/handoff", headers=headers, json={"items": many}).json()

    assert len(body["url"]) < 160


def test_code_is_single_use(client: TestClient, secret: str) -> None:
    headers = link(client, secret, 7103)
    code = client.post("/api/cart/handoff", headers=headers, json={"items": ITEMS}).json()["code"]
    service = {"Authorization": f"Bearer {service_token(secret)}"}

    assert client.post("/internal/cart-handoff/resolve", headers=service, json={"code": code}).status_code == 200
    assert client.post("/internal/cart-handoff/resolve", headers=service, json={"code": code}).status_code == 410


def test_unknown_code_is_404(client: TestClient, secret: str) -> None:
    service = {"Authorization": f"Bearer {service_token(secret)}"}
    assert client.post("/internal/cart-handoff/resolve", headers=service, json={"code": "nope"}).status_code == 404


def test_resolve_needs_a_service_token(client: TestClient, secret: str) -> None:
    headers = link(client, secret, 7104)
    code = client.post("/api/cart/handoff", headers=headers, json={"items": ITEMS}).json()["code"]

    # 토큰 없음
    assert client.post("/internal/cart-handoff/resolve", json={"code": code}).status_code == 401
    # 사용자 세션 토큰 — 서명은 맞지만 subject 가 다르다. 이게 막히지 않으면 아무 사용자나
    # 남의 장바구니 핸드오프를 들여다볼 수 있다.
    assert client.post("/internal/cart-handoff/resolve", headers=headers, json={"code": code}).status_code == 401
    # 다른 시크릿으로 서명한 서비스 토큰
    forged = {"Authorization": f"Bearer {service_token('some-other-secret-value-entirely')}"}
    assert client.post("/internal/cart-handoff/resolve", headers=forged, json={"code": code}).status_code == 401
    # 만료된 서비스 토큰
    stale = {"Authorization": f"Bearer {service_token(secret, expires_in=-1)}"}
    assert client.post("/internal/cart-handoff/resolve", headers=stale, json={"code": code}).status_code == 401


def test_session_token_subject_cannot_pose_as_service(client: TestClient, secret: str) -> None:
    posed = service_token(secret, subject=SESSION_SUBJECT)
    assert client.post(
        "/internal/cart-handoff/resolve",
        headers={"Authorization": f"Bearer {posed}"},
        json={"code": "whatever"},
    ).status_code == 401


def test_handoff_requires_a_session(client: TestClient) -> None:
    assert client.post("/api/cart/handoff", json={"items": ITEMS}).status_code == 401


def test_handoff_rejects_empty_basket(client: TestClient, secret: str) -> None:
    headers = link(client, secret, 7105)
    assert client.post("/api/cart/handoff", headers=headers, json={"items": []}).status_code == 400


def test_expired_code_is_gone(client: TestClient, secret: str) -> None:
    """결과지를 출력해두고 한참 뒤에 찍는 경우 — 만료는 410 이어야 한다(500 아님)."""
    from app.core.database import SessionLocal
    from app.models import CartHandoff

    headers = link(client, secret, 7106)
    code = client.post("/api/cart/handoff", headers=headers, json={"items": ITEMS}).json()["code"]

    db = SessionLocal()
    try:
        handoff = db.get(CartHandoff, code)
        handoff.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    service = {"Authorization": f"Bearer {service_token(secret)}"}
    assert client.post("/internal/cart-handoff/resolve", headers=service, json={"code": code}).status_code == 410
