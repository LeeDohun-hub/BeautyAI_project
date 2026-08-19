"""BeautyWEB 계정 연동 — 핸드오프 티켓 교환, 세션, 로그인 게이트.

여기서 검증하는 함정들:
  - 서명 키를 WEB 과 공유하므로 subject 를 안 보면 액세스 토큰/티켓/세션이 서로 통용된다.
  - 티켓이 URL 프래그먼트로 오므로 브라우저 히스토리에 남는다 → 1회용이어야 한다.
  - 세션이 붙었을 때 요청 본문의 user_id 를 그대로 믿으면 남의 이력을 읽고 쓸 수 있다.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import SESSION_SUBJECT, TICKET_SUBJECT
from app.main import app


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def secret() -> str:
    return get_settings().jwt_secret


def make_ticket(secret: str, *, expires_in: int = 120, **overrides) -> str:
    """WEB(AccountController#aiTicket)이 발급하는 티켓과 같은 모양."""
    claims = {
        "sub": TICKET_SUBJECT,
        "memberId": 4242,
        "jti": str(uuid.uuid4()),
        "name": "테스트회원",
        "loginId": "tester",
        "role": "USER",
        "gender": "female",
        "ageGroup": "30s",
        "skinType": "dry",
        "personalColor": "winter_deep",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    }
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm="HS256")


def test_exchange_creates_session_and_carries_profile(client: TestClient, secret: str) -> None:
    response = client.post("/api/auth/exchange", json={"ticket": make_ticket(secret, memberId=1001)})

    assert response.status_code == 200
    body = response.json()
    assert body["expires_in"] > 0
    user = body["user"]
    assert user["web_member_id"] == 1001
    # 프로필이 그대로 넘어와야 AI 설문 프리필과 퍼스널컬러 바로쓰기가 동작한다.
    assert user["gender"] == "female"
    assert user["age_group"] == "30s"
    assert user["skin_type"] == "dry"
    assert user["personal_color"] == "winter_deep"


def test_exchange_is_single_use(client: TestClient, secret: str) -> None:
    ticket = make_ticket(secret, memberId=1002)
    assert client.post("/api/auth/exchange", json={"ticket": ticket}).status_code == 200
    # 티켓은 URL 프래그먼트로 실려 와 히스토리에 남는다 — 두 번째는 막혀야 한다.
    assert client.post("/api/auth/exchange", json={"ticket": ticket}).status_code == 401


def test_same_member_reuses_one_ai_user(client: TestClient, secret: str) -> None:
    """다시 연동해도 사용자가 늘지 않아야 이력이 한 계정에 쌓인다."""
    first = client.post("/api/auth/exchange", json={"ticket": make_ticket(secret, memberId=1003)})
    second = client.post("/api/auth/exchange", json={"ticket": make_ticket(secret, memberId=1003)})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["user"]["id"] == second.json()["user"]["id"]


def test_expired_ticket_is_rejected(client: TestClient, secret: str) -> None:
    assert client.post(
        "/api/auth/exchange", json={"ticket": make_ticket(secret, expires_in=-1)}
    ).status_code == 401


def test_ticket_signed_with_other_secret_is_rejected(client: TestClient) -> None:
    assert client.post(
        "/api/auth/exchange", json={"ticket": make_ticket("a-completely-different-secret-value")}
    ).status_code == 401


def test_access_token_cannot_be_used_as_ticket(client: TestClient, secret: str) -> None:
    """WEB 과 서명 키가 같으므로 subject 검증이 유일한 방어선이다."""
    assert client.post(
        "/api/auth/exchange", json={"ticket": make_ticket(secret, sub="accessToken")}
    ).status_code == 401


def test_session_token_cannot_be_used_as_ticket(client: TestClient, secret: str) -> None:
    session = client.post("/api/auth/exchange", json={"ticket": make_ticket(secret, memberId=1004)})
    token = session.json()["token"]
    assert client.post("/api/auth/exchange", json={"ticket": token}).status_code == 401


def test_ticket_cannot_be_used_as_session(client: TestClient, secret: str) -> None:
    ticket = make_ticket(secret, memberId=1005)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {ticket}"}).status_code == 401


def test_me_requires_session(client: TestClient, secret: str) -> None:
    assert client.get("/api/auth/me").status_code == 401

    session = client.post("/api/auth/exchange", json={"ticket": make_ticket(secret, memberId=1006)})
    token = session.json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["web_member_id"] == 1006


def test_expired_session_is_rejected(client: TestClient, secret: str) -> None:
    stale = jwt.encode(
        {
            "sub": SESSION_SUBJECT,
            "userId": 1,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        secret,
        algorithm="HS256",
    )
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {stale}"}).status_code == 401


# ── 만료 뒤 프론트가 무엇을 보여주는가 (2026-08-19) ────────────────────────────
#
# 위 test_expired_session_is_rejected 는 서버가 401 을 준다는 것까지만 본다. 그런데
# **사용자가 실제로 보는 화면**은 그 401 을 프론트가 어떻게 읽느냐로 정해진다.
# 실제로 이랬다: 창구에 응답 인터셉터가 없어 401 이 흐름별 catch 로 떨어졌고, 거기서
# "백엔드 연결을 확인해 주세요" 가 떴다. 백엔드는 멀쩡하고 답은 '다시 로그인'이었다.
# 게이트도 부팅 때 한 번만 판단해 authUser 가 남아 있어 다시 서지 않았다.
# 세션 수명이 12시간이라 하루를 걸쳐 쓰는 사용자는 **반드시** 이 화면을 만난다.

FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"


def test_frontend_handles_401_centrally() -> None:
    """401 을 창구 한 곳에서 잡아 세션을 비우는지 본다."""
    client_ts = (FRONTEND_SRC / "api" / "client.ts").read_text(encoding="utf-8")
    assert "interceptors.response.use" in client_ts, (
        "client.ts 에 응답 인터셉터가 없습니다 — 세션 만료(401)가 흐름별 catch 로 떨어져 "
        "'백엔드 연결을 확인해 주세요' 로 잘못 안내됩니다."
    )
    assert "onSessionExpired" in client_ts, "만료를 화면에 알릴 통로(onSessionExpired)가 없습니다"


def test_frontend_rebuilds_gate_on_session_expiry() -> None:
    """만료를 잡기만 하고 게이트를 안 세우면 사용자는 여전히 답을 못 본다."""
    app_tsx = (FRONTEND_SRC / "App.tsx").read_text(encoding="utf-8")
    assert "onSessionExpired(" in app_tsx, "App 이 만료 신호를 구독하지 않습니다"
    assert "세션이 만료되었습니다. 다시 로그인해 주세요." in app_tsx, (
        "만료 안내 문구가 없습니다 — 게이트만 다시 떠도 사용자는 왜 튕겼는지 모릅니다."
    )
    i18n = (FRONTEND_SRC / "i18n.ts").read_text(encoding="utf-8")
    assert "'세션이 만료되었습니다. 다시 로그인해 주세요.'" in i18n, (
        "만료 안내에 일본어가 없습니다 — 일본어 모드에서 한국어가 나갑니다."
    )


def test_history_ignores_spoofed_user_id_when_session_present(client: TestClient, secret: str) -> None:
    """세션이 있으면 쿼리의 user_id 는 무시된다 — 남의 이력을 못 본다."""
    session = client.post("/api/auth/exchange", json={"ticket": make_ticket(secret, memberId=1007)})
    token = session.json()["token"]
    own_id = session.json()["user"]["id"]

    response = client.get(
        "/api/history",
        params={"user_id": own_id + 999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_broken_authorization_header_is_rejected(client: TestClient) -> None:
    """헤더가 있는데 틀리면 401. 조용히 익명으로 떨어지면 이력이 계정에 안 쌓인다."""
    assert client.get("/api/history", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_anonymous_use_still_works_by_default(client: TestClient) -> None:
    """REQUIRE_LOGIN 기본값(off)에서는 익명 호출이 그대로 동작해야 한다."""
    assert client.get("/api/history").status_code == 200
    assert client.get("/api/products").status_code == 200


def test_require_login_gates_the_api(client: TestClient, secret: str) -> None:
    """켜면 세션 없이는 401 — 프론트 게이트만으로는 API 가 열려 있다."""
    settings = get_settings()
    settings.require_login = True
    try:
        assert client.get("/api/history").status_code == 401
        assert client.get("/api/products").status_code == 401
        # 연동 엔드포인트는 게이트 밖이어야 한다. 아니면 로그인할 방법이 없다.
        assert client.get("/api/auth/config").status_code == 200
        session = client.post("/api/auth/exchange", json={"ticket": make_ticket(secret, memberId=1008)})
        assert session.status_code == 200
        token = session.json()["token"]
        assert client.get("/api/history", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    finally:
        settings.require_login = False


def test_auth_config_reports_gate_state(client: TestClient) -> None:
    body = client.get("/api/auth/config").json()
    assert body["require_login"] is False
    assert body["web_login_url"]


def test_web_api_base_url_falls_back_to_login_origin(client: TestClient) -> None:
    """WEB_API_BASE_URL 을 안 채워도 로그인 주소에서 유도돼야 한다.

    운영 .env 는 사람이 직접 고치는 파일이라, 필수로 만들면 빠뜨렸을 때
    '웹에 로그인했는데 AI 는 게이트' 가 조용히 되살아난다.
    """
    settings = get_settings()
    original_api, original_login = settings.web_api_base_url, settings.web_login_url
    try:
        settings.web_api_base_url = ""
        settings.web_login_url = "https://www.example.com/login"
        assert client.get("/api/auth/config").json()["web_api_base_url"] == "https://www.example.com/v1/api"

        # 명시값이 있으면 그것을 그대로 쓴다(로그인 주소와 API 호스트가 다른 배포).
        settings.web_api_base_url = "https://api.example.com/v1/api/"
        assert client.get("/api/auth/config").json()["web_api_base_url"] == "https://api.example.com/v1/api"
    finally:
        settings.web_api_base_url, settings.web_login_url = original_api, original_login


@pytest.mark.parametrize(
    "label",
    [
        "spring_bright",
        "spring_warm",
        "summer_light",
        "summer_mute",
        "autumn_warm",
        "autumn_mute",
        "winter_clear",
        "winter_deep",
    ],
)
def test_declared_personal_color_covers_every_web_label(client: TestClient, label: str) -> None:
    """웹 마이페이지의 8종이 전부 결과지로 풀려야 한다 — 하나라도 404 면 그 사람은 막힌다."""
    response = client.get("/api/personal-color/profile", params={"label": label})

    assert response.status_code == 200
    body = response.json()
    assert body["palette"]
    # 아이템매칭 검색어가 makeup 에서 나온다 — 비면 상품 컬럼이 통째로 빈다.
    assert body["makeup"]["lip"] and body["makeup"]["eye"] and body["makeup"]["base"]
    # 측정값이 아니라 본인 신고값이라 metrics 는 비어 있어야 한다.
    assert body["metrics"] == {}


def test_declared_personal_color_rejects_unknown_label(client: TestClient) -> None:
    assert client.get("/api/personal-color/profile", params={"label": "sprint_bright"}).status_code == 404


def test_ticket_profile_values_are_filtered(client: TestClient, secret: str) -> None:
    """티켓은 서명돼 있어도 값은 WEB 저장값이다 — AI 가 모르는 값은 버려야 한다."""
    response = client.post(
        "/api/auth/exchange",
        json={
            "ticket": make_ticket(
                secret,
                memberId=1009,
                gender="alien",
                ageGroup="200s",
                skinType="metallic",
                personalColor="mauve_season",
            )
        },
    )

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["gender"] is None
    assert user["age_group"] is None
    assert user["skin_type"] is None
    assert user["personal_color"] is None


# ── 내 데이터 삭제 (설계안 §11 '언제든 삭제 요청할 수 있게 한다') ─────────────────
# 보관 기간 자동 만료는 정책이 정해져야 하므로 만들지 않았다 — 삭제 '수단'만 만든 것이다.

def _session_token(client: TestClient, secret: str, member_id: int) -> str:
    res = client.post("/api/auth/exchange", json={"ticket": make_ticket(secret, memberId=member_id)})
    assert res.status_code == 200
    return res.json()["token"]


def test_delete_my_data_requires_session(client: TestClient) -> None:
    """세션이 없으면 401. user_id 파라미터를 받지 않으므로 남의 데이터는 애초에 지목할 수 없다."""
    assert client.delete("/api/me/data").status_code == 401


def test_delete_my_data_removes_only_own_rows(client: TestClient, secret: str) -> None:
    """다른 사용자의 행은 남아야 한다 — 이 검사가 없으면 '전체 삭제' 사고를 못 잡는다."""
    from app.core.database import SessionLocal
    from app.models import RecommendationHistory, SkinAnalysis, User

    mine = _session_token(client, secret, 910001)
    _session_token(client, secret, 910002)

    db = SessionLocal()
    try:
        me = db.query(User).filter(User.web_member_id == 910001).one()
        other = db.query(User).filter(User.web_member_id == 910002).one()

        def _analysis(uid: int) -> SkinAnalysis:
            return SkinAnalysis(user_id=uid, acne=1, pore=1, wrinkle=1,
                                redness=1, pigmentation=1, oiliness=1)

        db.add_all([
            _analysis(me.id), _analysis(other.id),
            RecommendationHistory(user_id=me.id, recommended_ingredients="[]", recommended_products="[]"),
            RecommendationHistory(user_id=other.id, recommended_ingredients="[]", recommended_products="[]"),
        ])
        db.commit()
        me_id, other_id = me.id, other.id
    finally:
        db.close()

    # ⚠ 절대 개수로 비교하면 안 된다 — test_beautyai.db 는 실행 간에 남아 이전 행이 섞인다
    #   (전체 스위트로 돌리면 이 테스트만 깨졌다). '남의 행이 하나도 안 줄었는가'를 본다.
    db = SessionLocal()
    try:
        before_other = db.query(SkinAnalysis).filter(SkinAnalysis.user_id == other_id).count()
    finally:
        db.close()

    res = client.delete("/api/me/data", headers={"Authorization": f"Bearer {mine}"})
    assert res.status_code == 200
    assert res.json()["deleted"]["skin_analyses"] >= 1

    db = SessionLocal()
    try:
        assert db.query(SkinAnalysis).filter(SkinAnalysis.user_id == me_id).count() == 0
        after_other = db.query(SkinAnalysis).filter(SkinAnalysis.user_id == other_id).count()
        assert after_other == before_other, "남의 데이터가 지워지면 안 된다"
    finally:
        db.close()
