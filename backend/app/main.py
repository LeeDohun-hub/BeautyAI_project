from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.routes import router
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.services.seed import seed_database

settings = get_settings()


def ensure_product_link_columns() -> None:
    """Add optional product link columns for existing local SQLite/MySQL databases."""
    inspector = inspect(engine)
    if "products" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("products")}
    statements = []
    if "product_url" not in columns:
        statements.append("ALTER TABLE products ADD COLUMN product_url VARCHAR(500) DEFAULT ''")
    if "image_url" not in columns:
        statements.append("ALTER TABLE products ADD COLUMN image_url VARCHAR(500) DEFAULT ''")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    Base.metadata.create_all(bind=engine)
    ensure_product_link_columns()
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    yield


app = FastAPI(title="BeautyAI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
