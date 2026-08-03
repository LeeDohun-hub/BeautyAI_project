from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def resolve_database_url(database_url: str) -> str:
    if not database_url.startswith("sqlite:///"):
        return database_url
    raw_path = database_url.removeprefix("sqlite:///")
    if raw_path == ":memory:":
        return database_url
    path = Path(raw_path)
    if path.is_absolute():
        return database_url
    return f"sqlite:///{settings.project_root / path}"


def guard_production_db(database_url: str) -> None:
    """운영 DB 를 로컬에서 실수로 여는 것을 막는다.

    조용히 경고만 찍으면 아무도 안 본다 — 엔진을 만들기 전에 예외로 끊는다.
    운영 컨테이너는 APP_ENV=production 을 받으므로 통과하고, 로컬에서 정말 필요하면
    ALLOW_PRODUCTION_DB=true 로 **의도를 밝히고** 연다.

    alembic 도 여기에 걸린다(alembic/env.py 가 이 모듈을 임포트한다). 배포는 마이그레이션을
    돌리지 않으므로 영향이 없고, 운영 마이그레이션은 원래 의도적이어야 하니 그대로 둔다.
    """
    marker = settings.production_db_marker.strip()
    if not marker or marker not in database_url:
        return
    if settings.is_production or settings.allow_production_db:
        return
    raise RuntimeError(
        f"운영 DB 로 접속하려고 합니다(APP_ENV={settings.app_env!r}).\n"
        "  - 개발용 DB 를 쓰려면 .env 의 DATABASE_URL 을 개발 DB 로 바꾸세요.\n"
        "  - 운영 데이터를 정말 봐야 한다면 ALLOW_PRODUCTION_DB=true 를 명시하세요.\n"
        "  - 운영 컨테이너인데 이 오류가 났다면 APP_ENV=production 이 빠진 것입니다.\n"
        "  - 운영 마이그레이션(alembic)이라면 ALLOW_PRODUCTION_DB=true 를 붙여 실행하세요."
    )


database_url = resolve_database_url(settings.database_url)
guard_production_db(database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
# expire_on_commit=False 가 핵심이다. 기본값(True)이면 commit 시점에 이미 로드한 객체가 전부
# 만료돼, 그 뒤 속성을 읽을 때마다 상품 하나씩 다시 조회한다(N+1).
# 실측(2026-07-28): 얼굴 추천은 상품 7,228건을 selectinload 로 한 번에 읽은 뒤 추천이력을
# commit 하는데, 그 직후 _product_out 이 name/brand/ingredients 를 만지면서 90초 동안
# products 211회·product_ingredients 225회·ingredients 211회를 재조회했다(DB 시간 77.9초).
# 운영 DB가 원거리 리전이라 왕복 지연이 곱해져 요청이 10분을 넘겼다.
# 커밋 이후에는 이미 읽은 값만 응답에 담으므로 만료시킬 이유가 없다.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
