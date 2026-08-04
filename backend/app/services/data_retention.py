"""개인정보 보관 기간 만료.

설계안 §11 의 마지막 항목. 삭제 **수단**은 `DELETE /api/me/data` 로 만들었고,
여기서는 **기간이 지난 것을 자동으로** 지운다.

⚠ 기본값(365일)은 개발팀이 정한 것이지 법무·정책이 확정한 값이 아니다.
   운영에서 DATA_RETENTION_DAYS 로 바꿀 수 있게 해 두었으니, 정책이 정해지면 그 값만 바꾼다.
   0 이면 만료를 하지 않는다(끄고 싶을 때).

왜 startup 이 아니라 스크립트인가: 부팅할 때마다 지우면, 설정을 잘못 넣은 상태로 배포한
순간 돌이킬 수 없다. 사람이 --dry-run 으로 먼저 확인하고 돌리게 한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import ChatHistory, RecommendationHistory, SkinAnalysis, Survey

# 지우는 대상. **users 는 넣지 않는다** — 웹에서 넘어온 연동 정보라 여기서 지우면
# 로그인 상태와 어긋난다(삭제 API 와 같은 이유). 계정 정리는 웹 소관이다.
EXPIRABLE = (
    ("skin_analyses", SkinAnalysis),
    ("surveys", Survey),
    ("recommendation_histories", RecommendationHistory),
    ("chat_histories", ChatHistory),
)


def count_expired(db: Session, days: int, now: datetime | None = None) -> dict[str, int]:
    """지울 대상이 몇 건인지만 센다. 실제로 지우기 전에 확인용."""
    if days <= 0:
        return {}
    cutoff = (now or datetime.utcnow()) - timedelta(days=days)
    return {
        name: db.query(model).filter(model.created_at < cutoff).count()
        for name, model in EXPIRABLE
    }


def expire_old_data(db: Session, days: int, now: datetime | None = None) -> dict[str, int]:
    """보관 기간이 지난 데이터를 지운다. 테이블별 삭제 건수를 돌려준다.

    days <= 0 이면 아무것도 하지 않는다 — **끄는 것이 기본 동작이어야** 설정 실수로
    데이터가 사라지지 않는다.
    """
    if days <= 0:
        return {}
    cutoff = (now or datetime.utcnow()) - timedelta(days=days)
    deleted = {
        name: db.query(model).filter(model.created_at < cutoff).delete(synchronize_session=False)
        for name, model in EXPIRABLE
    }
    db.commit()
    return {name: int(count or 0) for name, count in deleted.items()}
