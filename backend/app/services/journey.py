"""AI 앱의 회원 동선·선호 집계.

WEB 의 member_events 와 같은 발상이지만 흐름의 모양이 다르다. AI 는 물건을 파는 게 아니라
분석을 해 주는 앱이라서, 퍼널이 '기능 선택 → 사진 → 분석 → 추천 → 상품 클릭' 이다.
그래서 이탈의 큰 몫이 **분석 실패**에서 나오고, 그걸 따로 세는 게 이 모듈의 핵심 차이다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import JourneyEvent, Product
from app.schemas.api import (
    JourneyBatchIn,
    JourneyFunnelOut,
    JourneyFunnelStep,
    JourneyPreferenceOut,
    JourneyPreferenceScore,
    JourneyTrailOut,
    JourneyTrailStep,
    LabelCount,
)

#: 받아줄 행동 종류. 화이트리스트로 막지 않으면 오타 난 타입이 섞여 집계가 조용히 갈라지고
#: (cartadd 와 cart_add 가 따로 세어진다), 아무 문자열이나 밀어 넣어 표를 부풀릴 수 있다.
ALLOWED_TYPES = {
    "app_open",
    "gate_view",
    "module_open",
    "photo_ready",
    "analysis_done",
    "analysis_error",
    "recommend_view",
    "product_click",
    "cart_handoff",
    "survey_submit",
}

#: 아는 기능 이름. 프론트의 AppModule 과 같아야 한다.
ALLOWED_MODULES = {"home", "skin-care", "personal-color", "nail-design", "virtual-surgery"}

#: 퍼널 단계. 순서가 곧 의미다.
#: gate_view / analysis_error / cart_handoff / survey_submit 은 단계가 아니다 —
#: 모두를 거치는 길목이 아니라서 넣으면 깔때기가 엉킨다. 옆에서 따로 센다.
FUNNEL_STEPS: list[tuple[str, str]] = [
    ("app_open", "AI 앱 진입"),
    ("module_open", "기능 선택"),
    ("photo_ready", "사진 준비"),
    ("analysis_done", "분석 완료"),
    ("recommend_view", "추천 확인"),
    ("product_click", "상품 클릭"),
]

#: 선호 가중치. 결과를 본 것과 실제로 상품을 누른 것, 장바구니로 넘긴 것은 신호의 세기가
#: 다르다. 전부 1점으로 세면 '그냥 많이 보여진' 카테고리가 1위로 올라온다.
PREFERENCE_WEIGHT = {"recommend_view": 1.0, "product_click": 3.0, "cart_handoff": 6.0}

#: 한 번에 받는 이벤트 수 상한. 넘치면 앞에서부터 이만큼만 저장한다.
MAX_BATCH = 30

_MAX_LEN = {
    "session_id": 64,
    "type": 40,
    "module": 40,
    "lang": 10,
    "category": 80,
    "brand": 160,
    "platform": 40,
    "detail": 200,
}


def _cut(value: object, field: str, default: str = "") -> str:
    """컬럼 길이를 넘기면 자른다.

    프론트가 보낸 문자열이 컬럼보다 길면 INSERT 가 통째로 실패하는데, 수집이 실패해도
    사용자 화면은 아무 일 없어야 하므로 여기서 막는다.
    """
    if not isinstance(value, str) or not value.strip():
        return default
    return value.strip()[: _MAX_LEN[field]]


def record(db: Session, batch: JourneyBatchIn, user_id: int | None) -> int:
    """행동 묶음을 저장하고 실제로 저장된 건수를 돌려준다."""
    accepted = [event for event in batch.events if event.type in ALLOWED_TYPES][:MAX_BATCH]
    if not accepted:
        return 0

    # 상품은 한 번에 몰아서 조회한다. 이벤트마다 조회하면 30건짜리 요청 하나가 쿼리 31번이 된다.
    product_ids = {event.product_id for event in accepted if event.product_id}
    products: dict[int, Product] = {}
    if product_ids:
        # 브랜드는 관계라서 joinedload 없이 product.brand.name 을 읽으면 상품마다 한 번씩
        # 더 조회한다(N+1). 이 프로젝트에서 여러 번 데인 지점이라 처음부터 같이 읽는다.
        products = {
            product.id: product
            for product in db.query(Product)
            .options(joinedload(Product.brand))
            .filter(Product.id.in_(product_ids))
            .all()
        }

    session_id = _cut(batch.session_id, "session_id")
    lang = _cut(batch.lang, "lang", "ko")

    rows = []
    for event in accepted:
        product = products.get(event.product_id) if event.product_id else None
        # 상품이 우리 DB 에 있으면 서버 값이 이긴다. 퍼스널컬러 아이템매칭처럼 외부
        # 카탈로그에서 실시간으로 오는 상품만 클라이언트 값을 쓴다 — 그쪽은 애초에
        # DB 에 없어서 서버가 확인할 방법이 없다(길이만 자르고 받는다).
        rows.append(
            JourneyEvent(
                user_id=user_id,
                session_id=session_id,
                type=_cut(event.type, "type", "unknown"),
                # 모르는 기능 이름은 버린다 — 오타가 기능별 표를 갈라놓기 때문이다.
                module=_cut(event.module, "module") if event.module in ALLOWED_MODULES else "",
                lang=lang,
                product_id=product.id if product else None,
                category=product.category if product else _cut(event.category, "category"),
                brand=product.brand.name if product and product.brand else _cut(event.brand, "brand"),
                platform=_cut(event.platform, "platform"),
                price=float(product.price) if product else max(0.0, float(event.price or 0.0)),
                detail=_cut(event.detail, "detail"),
            )
        )

    db.add_all(rows)
    db.commit()
    return len(rows)


def _percent(part: int, whole: int) -> float:
    return 0.0 if whole <= 0 else round(part * 100.0 / whole, 1)


def funnel(db: Session, days: int, module: str | None = None, lang: str | None = None) -> JourneyFunnelOut:
    window = _clamp_days(days)
    since = datetime.utcnow() - timedelta(days=window)

    query = db.query(JourneyEvent).filter(JourneyEvent.created_at >= since)
    if lang:
        query = query.filter(JourneyEvent.lang == lang)

    # 세션마다 '무슨 행동을 했는지' 를 모아 둔다. 단계별로 따로 세면 앞 단계를 건너뛴
    # 세션 때문에 뒷 단계가 더 커져서 이탈률이 음수로 나온다(WEB 에서 실제로 겪은 함정).
    types_by_session: dict[str, set[str]] = defaultdict(set)
    modules: dict[str, set[str]] = defaultdict(set)
    errors: dict[str, int] = defaultdict(int)
    total = 0

    # 기능 필터는 세션 단위로 걸어야 한다. 행 단위로 걸면 app_open(module="home")이
    # 잘려나가 첫 단계가 0 이 되고 퍼널 전체가 무너진다.
    sessions_in_module: set[str] | None = None
    if module:
        sessions_in_module = {
            row[0]
            for row in db.query(JourneyEvent.session_id)
            .filter(JourneyEvent.created_at >= since, JourneyEvent.module == module)
            .distinct()
            .all()
        }

    for event in query.all():
        if sessions_in_module is not None and event.session_id not in sessions_in_module:
            continue
        total += 1
        if event.session_id:
            types_by_session[event.session_id].add(event.type)
            if event.module and event.module != "home":
                modules[event.module].add(event.session_id)
        if event.type == "analysis_error":
            errors[event.detail or "(사유 없음)"] += 1

    steps: list[JourneyFunnelStep] = []
    start = 0
    previous = 0
    for index, (event_type, label) in enumerate(FUNNEL_STEPS):
        required = {step[0] for step in FUNNEL_STEPS[: index + 1]}
        sessions = sum(1 for types in types_by_session.values() if required <= types)
        any_order = sum(1 for types in types_by_session.values() if event_type in types)
        if index == 0:
            start = sessions
            previous = sessions

        from_previous = _percent(sessions, previous)
        steps.append(
            JourneyFunnelStep(
                type=event_type,
                label=label,
                sessions=sessions,
                sessions_any_order=any_order,
                from_previous_percent=from_previous,
                from_start_percent=_percent(sessions, start),
                drop_off_percent=0.0 if previous <= 0 else round(100.0 - from_previous, 1),
            )
        )
        previous = sessions

    return JourneyFunnelOut(
        days=window,
        module=module or "all",
        lang=lang or "all",
        total_events=total,
        steps=steps,
        modules=_sorted_counts({name: len(ids) for name, ids in modules.items()}),
        errors=_sorted_counts(errors),
    )


def preference(db: Session, user_id: int, days: int) -> JourneyPreferenceOut:
    window = _clamp_days(days)
    since = datetime.utcnow() - timedelta(days=window)

    rows = (
        db.query(JourneyEvent)
        .filter(JourneyEvent.user_id == user_id, JourneyEvent.created_at >= since)
        .all()
    )

    modules: dict[str, int] = defaultdict(int)
    platforms: dict[str, int] = defaultdict(int)
    categories: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    brands: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    slot = {"recommend_view": 0, "product_click": 1, "cart_handoff": 2}

    for event in rows:
        if event.module and event.module != "home":
            modules[event.module] += 1
        if event.platform:
            platforms[event.platform] += 1
        index = slot.get(event.type)
        if index is None:
            continue
        if event.category:
            categories[event.category][index] += 1
        if event.brand:
            brands[event.brand][index] += 1

    return JourneyPreferenceOut(
        user_id=user_id,
        days=window,
        event_count=len(rows),
        top_modules=_sorted_counts(modules),
        top_categories=_scores(categories)[:8],
        top_brands=_scores(brands)[:8],
        top_platforms=_sorted_counts(platforms),
    )


def trail(db: Session, session_id: str) -> JourneyTrailOut:
    rows = (
        db.query(JourneyEvent)
        .filter(JourneyEvent.session_id == session_id)
        .order_by(JourneyEvent.created_at.asc(), JourneyEvent.id.asc())
        .limit(300)
        .all()
    )

    names: dict[int, str] = {}
    product_ids = {event.product_id for event in rows if event.product_id}
    if product_ids:
        names = {
            product.id: product.name
            for product in db.query(Product).filter(Product.id.in_(product_ids)).all()
        }

    steps: list[JourneyTrailStep] = []
    previous_at: datetime | None = None
    for event in rows:
        gap = None if previous_at is None else int((event.created_at - previous_at).total_seconds())
        steps.append(
            JourneyTrailStep(
                type=event.type,
                module=event.module,
                detail=event.detail or event.category or event.platform or "",
                product_name=names.get(event.product_id or -1, ""),
                at=event.created_at,
                seconds_from_previous=gap,
            )
        )
        previous_at = event.created_at

    first = rows[0] if rows else None
    return JourneyTrailOut(
        session_id=session_id,
        user_id=first.user_id if first else None,
        lang=first.lang if first else "",
        steps=steps,
    )


def recent_sessions(db: Session, days: int, limit: int = 20) -> list[LabelCount]:
    since = datetime.utcnow() - timedelta(days=_clamp_days(days))
    rows = (
        db.query(
            JourneyEvent.session_id,
            func.count(JourneyEvent.id),
            func.max(JourneyEvent.created_at),
        )
        .filter(JourneyEvent.created_at >= since, JourneyEvent.session_id != "")
        .group_by(JourneyEvent.session_id)
        .order_by(func.max(JourneyEvent.created_at).desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    return [LabelCount(label=row[0], total=row[1]) for row in rows]


def delete_for_user(db: Session, user_id: int) -> int:
    deleted = (
        db.query(JourneyEvent)
        .filter(JourneyEvent.user_id == user_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


def _clamp_days(days: int) -> int:
    if days <= 0:
        return 7
    return min(days, 365)


def _sorted_counts(counts: dict[str, int]) -> list[LabelCount]:
    return [
        LabelCount(label=label, total=total)
        for label, total in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def _scores(counts: dict[str, list[int]]) -> list[JourneyPreferenceScore]:
    scored = [
        JourneyPreferenceScore(
            label=label,
            score=round(
                PREFERENCE_WEIGHT["recommend_view"] * values[0]
                + PREFERENCE_WEIGHT["product_click"] * values[1]
                + PREFERENCE_WEIGHT["cart_handoff"] * values[2],
                1,
            ),
            views=values[0],
            clicks=values[1],
            handoffs=values[2],
        )
        for label, values in counts.items()
    ]
    return sorted([row for row in scored if row.score > 0], key=lambda row: row.score, reverse=True)
