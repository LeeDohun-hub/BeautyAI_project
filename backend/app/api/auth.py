"""웹 계정 연동 엔드포인트.

이 라우터에는 로그인 게이트(enforce_login)를 걸지 않는다 — 게이트를 통과하기 위해
호출하는 곳이라 걸면 서로 물린다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    burn_ticket,
    current_user,
    decode_handoff_ticket,
    issue_session_token,
    upsert_web_user,
)
from app.models import User
from app.schemas.api import (
    AuthConfigResponse,
    AuthExchangeRequest,
    AuthSessionResponse,
    AuthUser,
)

auth_router = APIRouter(prefix="/api/auth")


def _as_auth_user(user: User) -> AuthUser:
    return AuthUser(
        id=user.id,
        name=user.name,
        role=user.role,
        web_member_id=user.web_member_id,
        login_id=user.login_id,
        gender=user.gender,
        age_group=user.age_group,
        skin_type=user.skin_type,
        personal_color=user.personal_color,
    )


@auth_router.get("/config", response_model=AuthConfigResponse)
def auth_config() -> AuthConfigResponse:
    """프론트 게이트용 설정. 로그인 없이 부를 수 있어야 한다."""
    settings = get_settings()
    return AuthConfigResponse(
        require_login=settings.require_login,
        web_login_url=settings.web_login_url,
        jp_before_after=settings.jp_before_after,
    )


@auth_router.post("/exchange", response_model=AuthSessionResponse)
def exchange(payload: AuthExchangeRequest, db: Session = Depends(get_db)) -> AuthSessionResponse:
    """웹 핸드오프 티켓을 AI 세션으로 교환한다.

    티켓 검증 → jti 소각 → users upsert → 세션 발급. 소각을 upsert 보다 먼저 해서
    같은 티켓으로 두 번 들어오면 두 번째가 사용자 정보를 건드리기 전에 막히게 한다.
    """
    claims = decode_handoff_ticket(payload.ticket)
    burn_ticket(db, claims["jti"])
    user = upsert_web_user(db, claims)
    token, expires_in = issue_session_token(user.id)
    db.commit()
    return AuthSessionResponse(token=token, expires_in=expires_in, user=_as_auth_user(user))


@auth_router.get("/me", response_model=AuthUser)
def me(user: User = Depends(current_user)) -> AuthUser:
    """세션 확인 + 프로필 조회. 프론트가 새로고침 후 세션 유효성을 확인하는 데 쓴다."""
    return _as_auth_user(user)
