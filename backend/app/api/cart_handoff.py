"""결과지 QR → BeautyWEB 장바구니 핸드오프.

흐름:
    AI 결과지에서 상품을 담고 QR 생성
      → POST /api/cart/handoff (사용자 세션) → 짧은 코드 발급
      → QR = `<web_cart_url>?ai=<code>`
    폰으로 QR 스캔 → BeautyWEB 열림
      → BeautyWEB 백엔드가 POST /internal/cart-handoff/resolve (서비스 토큰) 로 목록을 받아
        회원 장바구니에 담는다.

QR 에 상품 목록을 직접 싣지 않는 이유는 CartHandoff 모델 주석 참조(요약: QR 이 너무 조밀해진다).
"""

import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import current_user, require_service_token
from app.models import CartHandoff, User
from app.schemas.api import (
    CartHandoffItem,
    CartHandoffRequest,
    CartHandoffResolveRequest,
    CartHandoffResolveResponse,
    CartHandoffResponse,
)

cart_handoff_router = APIRouter()


def _now() -> datetime:
    # DB 컬럼이 naive DateTime 이라 비교가 어긋나지 않게 UTC naive 로 맞춘다.
    return datetime.now(timezone.utc).replace(tzinfo=None)


@cart_handoff_router.post("/api/cart/handoff", response_model=CartHandoffResponse)
def create_handoff(
    payload: CartHandoffRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CartHandoffResponse:
    """결과지에 담은 상품으로 1회용 장바구니 코드를 만든다."""
    if not payload.items:
        raise HTTPException(status_code=400, detail="담긴 상품이 없습니다.")
    if user.web_member_id is None:
        # 웹 계정과 연결되지 않은 세션은 담을 장바구니가 없다. 프론트는 이 경우 QR 대신
        # 로그인 안내를 띄운다.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="웹 계정과 연동된 상태에서만 장바구니로 보낼 수 있습니다.",
        )

    settings = get_settings()
    expires_in = settings.cart_handoff_exp_minutes * 60
    handoff = CartHandoff(
        # 코드 자체가 베어러 자격증명이라 추측 불가능해야 한다(32바이트 = 43자 urlsafe).
        code=secrets.token_urlsafe(32),
        web_member_id=user.web_member_id,
        payload=json.dumps([item.model_dump() for item in payload.items], ensure_ascii=False),
        expires_at=_now() + timedelta(seconds=expires_in),
    )
    db.add(handoff)
    db.commit()

    separator = "&" if "?" in settings.web_cart_url else "?"
    return CartHandoffResponse(
        code=handoff.code,
        url=f"{settings.web_cart_url}{separator}ai={handoff.code}",
        expires_in=expires_in,
        item_count=len(payload.items),
    )


@cart_handoff_router.post(
    "/internal/cart-handoff/resolve",
    response_model=CartHandoffResolveResponse,
    dependencies=[Depends(require_service_token)],
)
def resolve_handoff(
    payload: CartHandoffResolveRequest,
    db: Session = Depends(get_db),
) -> CartHandoffResolveResponse:
    """BeautyWEB 백엔드 전용. 코드를 목록으로 바꾸고 그 자리에서 태운다.

    `/api` 밖에 둔다 — REQUIRE_LOGIN 게이트는 사용자 세션을 요구하는데 여기는 서버끼리
    부르는 곳이라 사용자 세션이 없다.
    """
    handoff = db.get(CartHandoff, payload.code.strip())
    if handoff is None:
        raise HTTPException(status_code=404, detail="장바구니 코드를 찾을 수 없습니다.")
    if handoff.consumed_at is not None:
        raise HTTPException(status_code=410, detail="이미 사용한 장바구니 코드입니다.")
    if handoff.expires_at <= _now():
        raise HTTPException(status_code=410, detail="장바구니 코드가 만료되었습니다.")

    handoff.consumed_at = _now()
    db.commit()

    items = [CartHandoffItem(**row) for row in json.loads(handoff.payload)]
    return CartHandoffResolveResponse(web_member_id=handoff.web_member_id, items=items)
