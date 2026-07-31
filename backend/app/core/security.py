"""BeautyWEB 계정 연동 — 핸드오프 티켓 검증과 AI 자체 세션.

흐름:
    WEB(로그인됨) → GET /v1/api/account/ai-ticket → 120초짜리 티켓(JWT)
    → AI 앱으로 `#t=<ticket>` 이동 → POST /api/auth/exchange
    → jti 소각 + users upsert → AI 세션 토큰(기본 12시간) 발급

WEB 의 액세스 토큰을 그대로 쓰지 않는 이유:
    1. WEB 액세스 토큰은 수명이 1분이다(AccountConstants.ACCESS_TOKEN_EXP_MINUTES).
    2. 갱신에 쓰는 리프레시 토큰은 HttpOnly·호스트 한정 쿠키라 AI 오리진에서는 못 읽는다.
    그래서 AI 가 자기 수명의 세션을 따로 발급한다.

서명 키(settings.jwt_secret)는 WEB 과 같은 값이어야 한다. 키가 같으므로 **subject 검증이
필수다** — 안 그러면 1분짜리 액세스 토큰이 티켓으로, 티켓이 세션으로 서로 통용된다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import UsedTicket, User

ALGORITHM = "HS256"
# WEB 이 발급하는 핸드오프 티켓의 subject(AccountConstants.AI_TICKET_NAME 과 같아야 한다).
TICKET_SUBJECT = "aiHandoff"
# AI 가 발급하는 자체 세션 토큰의 subject.
SESSION_SUBJECT = "aiSession"
# BeautyWEB 백엔드가 장바구니 핸드오프를 조회할 때 쓰는 서비스 토큰의 subject.
# 사용자 토큰이 아니라 **서버끼리** 쓰는 것이라, 사용자 세션으로는 이 경로를 못 연다.
SERVICE_SUBJECT = "beautywebService"

# 웹에서 넘어온 프로필 중 우리가 신뢰하고 쓰는 값. 티켓은 서명돼 있지만, 값 자체는
# WEB 저장값이라 AI 설문과 어긋난 문자열이 들어올 수 있다 — 여기서 한 번 더 거른다.
ALLOWED_GENDERS = {"female", "male"}
ALLOWED_AGE_GROUPS = {"baby", "child", "10s", "20s", "30s", "40s", "50s"}
ALLOWED_SKIN_TYPES = {"dry", "oily", "combination", "normal", "sensitive"}
ALLOWED_PERSONAL_COLORS = {
    "spring_bright",
    "spring_warm",
    "summer_light",
    "summer_mute",
    "autumn_warm",
    "autumn_mute",
    "winter_clear",
    "winter_deep",
}


class AuthError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _sanitize(value: object, allowed: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in allowed else None


def decode_handoff_ticket(token: str) -> dict:
    """WEB 핸드오프 티켓을 검증하고 클레임을 돌려준다. 실패하면 401."""
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("연동 티켓이 만료되었습니다. 웹에서 다시 시도해주세요.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("연동 티켓이 올바르지 않습니다.") from exc

    # 서명 키를 WEB 과 공유하므로 subject 로 용도를 못박는다.
    if claims.get("sub") != TICKET_SUBJECT:
        raise AuthError("연동 티켓이 올바르지 않습니다.")
    if not isinstance(claims.get("memberId"), int):
        raise AuthError("연동 티켓에 회원 정보가 없습니다.")
    if not isinstance(claims.get("jti"), str) or not claims["jti"]:
        raise AuthError("연동 티켓이 올바르지 않습니다.")
    return claims


def burn_ticket(db: Session, jti: str) -> None:
    """티켓 jti 를 1회용으로 태운다. 이미 쓴 티켓이면 401."""
    if db.get(UsedTicket, jti) is not None:
        raise AuthError("이미 사용한 연동 티켓입니다. 웹에서 다시 시도해주세요.")
    db.add(UsedTicket(jti=jti))
    db.flush()


def upsert_web_user(db: Session, claims: dict) -> User:
    """티켓의 회원 정보로 AI 쪽 사용자를 만들거나 갱신한다."""
    member_id = int(claims["memberId"])
    user = db.query(User).filter(User.web_member_id == member_id).one_or_none()
    if user is None:
        user = User(web_member_id=member_id)
        db.add(user)

    name = claims.get("name")
    login_id = claims.get("loginId")
    user.name = name.strip() if isinstance(name, str) and name.strip() else "Guest"
    user.login_id = login_id if isinstance(login_id, str) else None
    user.role = "admin" if str(claims.get("role", "")).upper() == "ADMIN" else "customer"
    user.gender = _sanitize(claims.get("gender"), ALLOWED_GENDERS)
    user.age_group = _sanitize(claims.get("ageGroup"), ALLOWED_AGE_GROUPS)
    user.skin_type = _sanitize(claims.get("skinType"), ALLOWED_SKIN_TYPES)
    user.personal_color = _sanitize(claims.get("personalColor"), ALLOWED_PERSONAL_COLORS)
    db.flush()
    return user


def issue_session_token(user_id: int) -> tuple[str, int]:
    """AI 자체 세션 토큰과 만료까지 남은 초를 돌려준다."""
    settings = get_settings()
    expires_in = settings.ai_session_exp_hours * 3600
    payload = {
        "sub": SESSION_SUBJECT,
        "userId": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM), expires_in


def decode_session_token(token: str) -> int:
    """AI 세션 토큰에서 사용자 id 를 꺼낸다. 실패하면 401."""
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("세션이 만료되었습니다. 웹에서 다시 로그인해주세요.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("세션이 올바르지 않습니다.") from exc

    if claims.get("sub") != SESSION_SUBJECT:
        raise AuthError("세션이 올바르지 않습니다.")
    user_id = claims.get("userId")
    if not isinstance(user_id, int):
        raise AuthError("세션이 올바르지 않습니다.")
    return user_id


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def optional_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    """세션이 있으면 사용자를, 없으면 None. 익명 사용을 막지 않는다.

    분석 결과를 계정에 붙이는 용도라 헤더가 아예 없으면 조용히 넘어간다. 다만 헤더가
    **있는데 틀린** 경우는 401 로 알린다 — 만료된 세션으로 계속 쓰다가 이력이 조용히
    익명으로 쌓이는 게 더 나쁘다.
    """
    token = _bearer(authorization)
    if token is None:
        return None
    return db.get(User, decode_session_token(token))


def current_user(user: User | None = Depends(optional_user)) -> User:
    """세션 필수. 없으면 401."""
    if user is None:
        raise AuthError("로그인이 필요합니다.")
    return user


def require_service_token(authorization: str | None = Header(default=None)) -> None:
    """BeautyWEB 백엔드만 부를 수 있는 경로를 지킨다.

    사용자 세션과 같은 키로 서명되므로 subject 로 용도를 갈라야 한다 — 안 그러면 아무
    사용자나 자기 세션 토큰으로 남의 장바구니 핸드오프를 조회할 수 있다.
    """
    token = _bearer(authorization)
    if token is None:
        raise AuthError("서비스 토큰이 필요합니다.")
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError as exc:  # 만료도 여기 걸린다(ExpiredSignatureError 가 하위 클래스)
        raise AuthError("서비스 토큰이 올바르지 않습니다.") from exc

    if claims.get("sub") != SERVICE_SUBJECT:
        raise AuthError("서비스 토큰이 올바르지 않습니다.")


def enforce_login(user: User | None = Depends(optional_user)) -> None:
    """settings.require_login 이 켜져 있을 때만 세션을 강제한다(라우터 전역 의존성).

    프론트 게이트만으로는 API 가 그대로 열려 있어서 운영에서는 켠다. 기본값이 꺼짐인 건
    로컬·테스트에서 익명 호출로 기능을 그대로 확인할 수 있게 하기 위해서다.
    """
    if get_settings().require_login and user is None:
        raise AuthError("로그인이 필요합니다.")
