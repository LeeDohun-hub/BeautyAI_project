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


database_url = resolve_database_url(settings.database_url)
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
