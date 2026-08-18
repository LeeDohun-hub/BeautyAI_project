"""AI 앱의 회원 동선·선호.

여기서 지키는 것:
  - 수집은 로그인 없이 열려 있고, 통계 조회는 관리자만 볼 수 있다.
  - 퍼널은 절대 넓어지지 않는다(앞 단계를 건너뛴 세션이 있어도 이탈률이 음수가 안 된다).
  - 사용자가 보낸 상품 정보보다 서버 DB 값이 이긴다.
  - "내 데이터 삭제" 가 동선까지 지운다.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base, SessionLocal
from app.core.security import issue_session_token
from app.main import app
from app.models import Brand, JourneyEvent, Product, User
from app.schemas.api import JourneyBatchIn, JourneyEventIn
from app.services import journey


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """HTTP 게이트 검사용. lifespan 이 앱 DB 에 표를 만든다."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db(tmp_path) -> Generator[Session, None, None]:
    """집계 로직 검사용 — 테스트마다 빈 DB 를 새로 판다.

    앱 DB 를 공유하면 앞 테스트가 남긴 세션이 퍼널 숫자에 섞여, 실패했을 때 원인이
    내 코드인지 남은 데이터인지 알 수 없게 된다.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'journey.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def app_db() -> Generator[Session, None, None]:
    """HTTP 테스트가 쓰는 앱 DB 세션. 남긴 이벤트는 반드시 치운다."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.query(JourneyEvent).delete()
        session.commit()
        session.close()


def make_user(db: Session, role: str = "customer") -> User:
    user = User(name=f"tester-{uuid.uuid4().hex[:6]}", role=role)
    db.add(user)
    db.commit()
    return user


def batch(session_id: str, events: list[JourneyEventIn], lang: str = "ko") -> JourneyBatchIn:
    return JourneyBatchIn(session_id=session_id, lang=lang, events=events)


def event(event_type: str, **kwargs) -> JourneyEventIn:
    return JourneyEventIn(type=event_type, **kwargs)


# ── 수집 ──────────────────────────────────────────────────────────────────────


def test_unknown_event_types_are_dropped(db: Session) -> None:
    saved = journey.record(
        db,
        batch("s-1", [event("app_open"), event("appopen"), event("<script>")]),
        None,
    )

    assert saved == 1
    assert [row.type for row in db.query(JourneyEvent).all()] == ["app_open"]


def test_unknown_modules_are_blanked_instead_of_splitting_the_table(db: Session) -> None:
    journey.record(
        db,
        batch("s-1", [event("module_open", module="skin-care"), event("module_open", module="skincare")]),
        None,
    )

    modules = sorted(row.module for row in db.query(JourneyEvent).all())
    # 오타("skincare")는 기능별 표를 갈라놓으므로 빈 값으로 떨어져야 한다.
    assert modules == ["", "skin-care"]


def test_anonymous_visits_are_kept_without_a_user_id(db: Session) -> None:
    journey.record(db, batch("s-guest", [event("gate_view")]), None)

    assert db.query(JourneyEvent).one().user_id is None


def test_server_product_data_beats_whatever_the_client_sent(db: Session) -> None:
    brand = Brand(name=f"anua-{uuid.uuid4().hex[:6]}", description="")
    db.add(brand)
    db.flush()
    product = Product(brand_id=brand.id, name="수분 토너", category="skincare", price=28000)
    db.add(product)
    db.commit()

    journey.record(
        db,
        batch(
            "s-1",
            [event("product_click", product_id=product.id, category="위조", brand="위조", price=999999)],
        ),
        None,
    )

    row = db.query(JourneyEvent).one()
    assert row.category == "skincare"
    assert row.brand == brand.name
    assert row.price == 28000


def test_products_outside_our_db_still_record_their_category(db: Session) -> None:
    # 퍼스널컬러 아이템매칭은 외부 카탈로그에서 실시간으로 오므로 product_id 가 없다.
    # 그래도 카테고리·채널은 남아야 선호 집계가 가능하다.
    journey.record(
        db,
        batch("s-1", [event("product_click", category="lip", brand="romand", platform="rakuten")]),
        None,
    )

    row = db.query(JourneyEvent).one()
    assert (row.category, row.brand, row.platform) == ("lip", "romand", "rakuten")


def test_batch_is_capped_so_one_request_cannot_flood_the_table(db: Session) -> None:
    flood = [event("app_open") for _ in range(100)]

    assert journey.record(db, batch("s-1", flood), None) == journey.MAX_BATCH


# ── 퍼널 ──────────────────────────────────────────────────────────────────────


def test_funnel_counts_sessions_not_events(db: Session) -> None:
    journey.record(
        db,
        batch(
            "s-1",
            [
                event("app_open"),
                event("module_open", module="skin-care"),
                event("module_open", module="skin-care"),
                event("photo_ready", module="skin-care"),
            ],
        ),
        None,
    )
    journey.record(db, batch("s-2", [event("app_open")]), None)

    steps = {step.type: step for step in journey.funnel(db, 7).steps}

    assert steps["app_open"].sessions == 2
    assert steps["module_open"].sessions == 1
    assert steps["photo_ready"].sessions == 1
    assert steps["analysis_done"].sessions == 0


def test_a_step_is_never_bigger_than_the_one_before_it(db: Session) -> None:
    # 사진부터 바로 올린 세션(기능 선택 이벤트가 안 잡힌 경우)이 있어도
    # 깔때기는 넓어지면 안 된다. WEB 에서 이탈률 -100% 로 드러났던 함정이다.
    journey.record(
        db,
        batch(
            "s-full",
            [
                event("app_open"),
                event("module_open", module="personal-color"),
                event("photo_ready", module="personal-color"),
                event("analysis_done", module="personal-color"),
            ],
        ),
        None,
    )
    journey.record(
        db,
        batch("s-skip", [event("app_open"), event("photo_ready"), event("analysis_done")]),
        None,
    )

    steps = journey.funnel(db, 7).steps
    for previous, current in zip(steps, steps[1:]):
        assert current.sessions <= previous.sessions
        assert 0.0 <= current.drop_off_percent <= 100.0

    photo = next(step for step in steps if step.type == "photo_ready")
    assert photo.sessions == 1          # 앞 단계를 전부 거친 세션
    assert photo.sessions_any_order == 2  # 실제로 사진을 올린 세션


def test_analysis_errors_are_counted_separately_with_their_reason(db: Session) -> None:
    journey.record(
        db,
        batch(
            "s-1",
            [
                event("app_open"),
                event("module_open", module="skin-care"),
                event("photo_ready", module="skin-care"),
                event("analysis_error", module="skin-care", detail="얼굴 미검출"),
            ],
        ),
        None,
    )

    result = journey.funnel(db, 7)

    # 실패는 퍼널 단계가 아니라 옆에 사유별로 붙는다 — AI 앱 이탈의 큰 원인이라서다.
    assert [(row.label, row.total) for row in result.errors] == [("얼굴 미검출", 1)]
    assert all(step.type != "analysis_error" for step in result.steps)


def test_module_filter_keeps_the_first_step_intact(db: Session) -> None:
    # app_open 은 module 이 비어 있다. 행 단위로 기능을 거르면 첫 단계가 0 이 되어
    # 퍼널 전체가 무너지므로, 필터는 세션 단위로 걸어야 한다.
    journey.record(
        db,
        batch("s-1", [event("app_open"), event("module_open", module="nail-design")]),
        None,
    )
    journey.record(
        db,
        batch("s-2", [event("app_open"), event("module_open", module="skin-care")]),
        None,
    )

    nail = journey.funnel(db, 7, module="nail-design")

    assert nail.steps[0].sessions == 1
    assert nail.steps[1].sessions == 1


# ── 선호 ──────────────────────────────────────────────────────────────────────


def test_preference_weighs_clicks_above_impressions(db: Session) -> None:
    user = make_user(db)
    # 립은 여섯 번 보여지기만 했고, 스킨케어는 한 번 보고 눌러서 장바구니로 넘겼다.
    journey.record(
        db,
        batch(
            "s-1",
            [
                event("recommend_view", category="lip"),
                event("recommend_view", category="lip"),
                event("recommend_view", category="skincare"),
                event("product_click", category="skincare"),
                event("cart_handoff", category="skincare"),
            ],
        ),
        user.id,
    )

    categories = journey.preference(db, user.id, 90).top_categories

    assert categories[0].label == "skincare"
    assert categories[0].score == 10.0  # 1 + 3 + 6
    assert categories[1].label == "lip"
    assert categories[1].score == 2.0


def test_trail_keeps_order_and_measures_gaps(db: Session) -> None:
    user = make_user(db)
    journey.record(
        db,
        batch(
            "s-1",
            [
                event("app_open"),
                event("module_open", module="virtual-surgery"),
                event("analysis_error", module="virtual-surgery", detail="얼굴 미검출"),
            ],
        ),
        user.id,
    )

    trail = journey.trail(db, "s-1")

    assert trail.user_id == user.id
    assert [step.type for step in trail.steps] == ["app_open", "module_open", "analysis_error"]
    # 첫 걸음은 직전이 없으므로 간격이 None 이어야 한다(0 이 아니다).
    assert trail.steps[0].seconds_from_previous is None
    assert trail.steps[2].detail == "얼굴 미검출"


def test_deleting_my_data_removes_only_my_rows(db: Session) -> None:
    mine = make_user(db)
    other = make_user(db)
    journey.record(db, batch("s-1", [event("app_open")]), mine.id)
    journey.record(db, batch("s-2", [event("app_open")]), other.id)

    assert journey.delete_for_user(db, mine.id) == 1
    assert db.query(JourneyEvent).one().user_id == other.id


# ── HTTP 게이트 ───────────────────────────────────────────────────────────────


def test_anonymous_visitors_can_send_events_but_not_read_statistics(
    client: TestClient, app_db: Session
) -> None:
    posted = client.post(
        "/api/journey/events",
        json={"session_id": "s-http", "lang": "ko", "events": [{"type": "gate_view"}]},
    )
    assert posted.status_code == 200
    assert posted.json() == {"saved": 1}

    assert client.get("/api/journey/funnel").status_code == 401


def test_ordinary_members_cannot_read_statistics_or_other_peoples_taste(
    client: TestClient, app_db: Session
) -> None:
    user = make_user(app_db)
    other = make_user(app_db)
    token, _ = issue_session_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/journey/funnel", headers=headers).status_code == 403
    assert client.get("/api/journey/preferences", headers=headers).status_code == 200
    assert (
        client.get(f"/api/journey/preferences?user_id={other.id}", headers=headers).status_code == 403
    )


def test_admins_can_read_statistics(client: TestClient, app_db: Session) -> None:
    admin = make_user(app_db, role="admin")
    token, _ = issue_session_token(admin.id)

    response = client.get("/api/journey/funnel?days=7", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert [step["type"] for step in response.json()["steps"]] == [
        step[0] for step in journey.FUNNEL_STEPS
    ]


def test_malformed_events_are_swallowed_instead_of_breaking_the_page(client: TestClient) -> None:
    response = client.post(
        "/api/journey/events",
        json={"session_id": "s-bad", "events": [{"type": "nope"}]},
    )

    assert response.status_code == 200
    assert response.json() == {"saved": 0}
