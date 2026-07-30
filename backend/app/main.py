import logging
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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


# 워밍 완료 신호. /ready 가 이걸 보고 준비 상태를 알린다.
# 워밍 전에는 첫 요청이 카탈로그·모델 로딩(≈20초)과 원격 DB 전량 조회를 혼자 떠안아
# 30초씩 걸린다(실측). 그동안 트래픽이 붙지 않게 하는 게 목적이다.
_warm_done = threading.Event()


def _warm_caches() -> None:
    """색조 후보 id·상품 카탈로그를 미리 올려 첫 요청의 콜드 비용을 없앤다."""
    from app.services import amazon_catalog, oliveyoung_catalog
    from app.services.recommender import _personal_color_candidate_ids, ingredient_index

    # ⚠ SessionLocal() 도 try 안에서 만든다. 밖에 두면 DB 가 잠깐 안 뜬 상태에서 예외가
    #   그대로 새어나가 finally 를 못 타고, /ready 가 영원히 503 이 되어 배포가 멈춘다.
    db = None
    try:
        db = SessionLocal()
        _personal_color_candidate_ids(db)
        # 피부케어 랭킹이 쓰는 상품 성분 인덱스(원격 DB 1.2초). 안 데우면 첫 추천 요청이 떠안는다.
        ingredient_index(db)
        oliveyoung_catalog.catalog_available()
        amazon_catalog.catalog_available("us")
        amazon_catalog.catalog_available("jp")
        # 토큰 문서빈도(희귀어 게이트용). 카탈로그 전체를 한 번 훑으므로 함께 데운다.
        amazon_catalog._catalog_doc_freq("us")
        amazon_catalog._catalog_doc_freq("jp")
        # 카탈로그 주입용 카테고리 풀도 미리 만든다 — 첫 요청이 분류 비용(카테고리당 수 초)을
        # 혼자 떠안으면 아마존 탭 첫 조회가 수십 초가 된다(실측 콜드 55초).
        from app.api.routes import _amazon_category_pool

        for region in ("us", "jp"):
            for category in ("lip", "blush", "eye", "base", "nail"):
                _amazon_category_pool(region, category)
    except Exception:  # noqa: BLE001 - 워밍업 실패는 치명적이지 않다(요청 시 지연 로딩).
        logging.getLogger(__name__).warning("cache warmup failed", exc_info=True)
    finally:
        if db is not None:
            db.close()
        # 실패해도 신호는 세운다. 안 그러면 /ready 가 영원히 503 이라 배포가 멈춘다
        # (워밍은 최적화일 뿐이고, 실패 시에도 요청 시 지연 로딩으로 동작한다).
        _warm_done.set()
        logging.getLogger(__name__).info("cache warmup finished")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    Base.metadata.create_all(bind=engine)
    ensure_product_link_columns()
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    # 무거운 로컬 인덱스를 백그라운드로 데운다. 아이템매칭 첫 요청이 색조 후보 스캔(전체
    # 상품 1회 로딩)과 아마존/올리브영 카탈로그 로딩을 혼자 떠안아 ~20초가 걸렸다(실측).
    # 기동을 막지 않게 스레드로 돌리고, 실패해도 요청 시 지연 로딩되므로 무시한다.
    threading.Thread(target=_warm_caches, name="warm-caches", daemon=True).start()
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
    """생존 확인(liveness). 프로세스가 살아 있으면 항상 200 — 재시작 판단용."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> JSONResponse:
    """트래픽 수용 준비(readiness). 워밍이 끝나야 200.

    ⚠ liveness 와 분리해야 한다. /health 로 둘 다 보면, 워밍 중 503 을 '죽었다'로 읽고
    오케스트레이터가 컨테이너를 계속 재시작한다(재시작할 때마다 워밍을 다시 하므로 영원히
    준비되지 않는다). 로드밸런서·compose healthcheck 는 이쪽을 봐야 첫 사용자가 30초를
    기다리지 않는다.
    """
    if _warm_done.is_set():
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "warming"}, status_code=503)
