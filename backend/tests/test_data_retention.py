"""보관 기간 자동 만료.

되돌릴 수 없는 삭제라, **덜 지우는 쪽으로 틀리게** 만들어 두고 그것을 검사한다:
  · days <= 0 이면 아무것도 안 지운다(설정 실수가 데이터 소실이 되면 안 된다)
  · 경계(정확히 N일)는 남긴다
  · users 는 절대 안 지운다(웹 연동 정보 — 지우면 로그인 상태와 어긋난다)
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import ChatHistory, RecommendationHistory, SkinAnalysis, Survey, User
from app.services.data_retention import count_expired, expire_old_data

NOW = datetime(2026, 8, 4, 12, 0, 0)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retention.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


def _seed(db, ages_in_days: list[int]) -> User:
    user = User(email="a@b.com", name="테스트")
    db.add(user)
    db.commit()
    for age in ages_in_days:
        made = NOW - timedelta(days=age)
        db.add_all([
            SkinAnalysis(user_id=user.id, acne=1, pore=1, wrinkle=1, redness=1,
                         pigmentation=1, oiliness=1, created_at=made),
            Survey(user_id=user.id, skin_type="combination", created_at=made),
            RecommendationHistory(user_id=user.id, recommended_ingredients="[]",
                                  recommended_products="[]", created_at=made),
            ChatHistory(user_id=user.id, message="q", answer="a", created_at=made),
        ])
    db.commit()
    return user


def test_expires_only_older_than_the_period(db) -> None:
    _seed(db, [400, 370, 100, 1])
    deleted = expire_old_data(db, days=365, now=NOW)
    assert deleted["skin_analyses"] == 2, "400일·370일 두 건만 지워져야 한다"
    assert db.query(SkinAnalysis).count() == 2


def test_boundary_is_kept(db) -> None:
    """정확히 N일 된 것은 남긴다 — 경계에서 틀리면 '덜 지우는' 쪽이 안전하다."""
    _seed(db, [365])
    assert expire_old_data(db, days=365, now=NOW)["skin_analyses"] == 0
    assert db.query(SkinAnalysis).count() == 1


@pytest.mark.parametrize("days", [0, -1])
def test_zero_or_negative_deletes_nothing(db, days: int) -> None:
    """설정 실수(빈 값 → 0)가 데이터 소실이 되면 안 된다."""
    _seed(db, [9999])
    assert expire_old_data(db, days=days, now=NOW) == {}
    assert db.query(SkinAnalysis).count() == 1


def test_never_deletes_the_account(db) -> None:
    """users 는 웹 연동 정보다. 지우면 로그인 상태와 어긋난다(삭제 API 와 같은 규칙)."""
    _seed(db, [9999])
    expire_old_data(db, days=1, now=NOW)
    assert db.query(User).count() == 1


def test_count_matches_what_gets_deleted(db) -> None:
    """--dry-run 이 실제와 다르면 확인하는 의미가 없다."""
    _seed(db, [400, 400, 10])
    planned = count_expired(db, days=365, now=NOW)
    actual = expire_old_data(db, days=365, now=NOW)
    assert planned == actual


def test_all_four_tables_are_covered(db) -> None:
    _seed(db, [400])
    expire_old_data(db, days=365, now=NOW)
    for model in (SkinAnalysis, Survey, RecommendationHistory, ChatHistory):
        assert db.query(model).count() == 0, f"{model.__tablename__} 가 안 지워졌다"
