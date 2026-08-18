"""회원 동선·선호 수집과 조회.

인증이 경로마다 다르다는 점이 핵심이다.

* ``POST /api/journey/events`` — **로그인 없이 열려 있다.** 이 라우터를 메인 router 와
  따로 만든 이유가 이것이다. 메인 router 는 ``dependencies=[Depends(enforce_login)]`` 를
  달고 있어서, REQUIRE_LOGIN 이 켜진 운영에서는 로그인 게이트 앞에서 돌아서는 사람의
  행동이 하나도 안 쌓인다 — 그런데 그 구간이 바로 이탈이 가장 큰 곳이다.
* **그 밖의 경로** — 남의 동선과 취향이 보이는 곳이므로 관리자만 연다.
  본인 선호 조회만 예외로 자기 것에 한해 열려 있다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import current_user, optional_user
from app.models import User
from app.schemas.api import (
    JourneyBatchIn,
    JourneyFunnelOut,
    JourneyPreferenceOut,
    JourneyTrailOut,
    LabelCount,
)
from app.services import journey

journey_router = APIRouter(prefix="/api/journey")


def require_admin(user: User = Depends(current_user)) -> User:
    """관리자만. 역할은 웹 핸드오프 티켓의 role 클레임에서 온다(security.upsert_web_user)."""
    if (user.role or "").lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자만 볼 수 있습니다.")
    return user


@journey_router.post("/events")
def collect(
    payload: JourneyBatchIn,
    db: Session = Depends(get_db),
    session_user: User | None = Depends(optional_user),
) -> dict[str, int]:
    """행동 묶음 저장.

    실패해도 200 을 준다. 수집은 부가 기능인데 여기서 4xx/5xx 가 나가면 사용자 화면과
    아무 상관 없는 에러가 콘솔을 채우고 디버깅을 방해한다. 실제로 몇 건이 저장됐는지는
    응답 숫자로 확인할 수 있다(화이트리스트에 걸린 건 빠진다).
    """
    try:
        saved = journey.record(db, payload, session_user.id if session_user else None)
    except Exception:  # noqa: BLE001 - 수집 실패가 사용자 흐름을 막으면 안 된다.
        db.rollback()
        saved = 0
    return {"saved": saved}


@journey_router.get("/funnel", response_model=JourneyFunnelOut)
def funnel(
    days: int = 7,
    module: str | None = None,
    lang: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> JourneyFunnelOut:
    return journey.funnel(db, days, module, lang)


@journey_router.get("/sessions", response_model=list[LabelCount])
def sessions(
    days: int = 7,
    limit: int = 20,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[LabelCount]:
    return journey.recent_sessions(db, days, limit)


@journey_router.get("/sessions/{session_id}", response_model=JourneyTrailOut)
def trail(
    session_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> JourneyTrailOut:
    return journey.trail(db, session_id)


@journey_router.get("/preferences", response_model=JourneyPreferenceOut)
def preferences(
    user_id: int | None = None,
    days: int = 90,
    db: Session = Depends(get_db),
    session_user: User = Depends(current_user),
) -> JourneyPreferenceOut:
    """선호 요약. user_id 를 안 주면 자기 것, 주면 관리자만.

    파라미터를 그냥 믿으면 로그인한 아무나 남의 취향을 조회할 수 있는 API 가 된다.
    """
    target = session_user.id if user_id is None else user_id
    if target != session_user.id and (session_user.role or "").lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자만 볼 수 있습니다.")
    return journey.preference(db, target, days)


@journey_router.delete("/me")
def delete_mine(
    db: Session = Depends(get_db),
    session_user: User = Depends(current_user),
) -> dict[str, int]:
    """내 동선 기록만 삭제. 개인정보라 본인이 언제든 지울 수 있어야 한다."""
    return {"deleted": journey.delete_for_user(db, session_user.id)}
