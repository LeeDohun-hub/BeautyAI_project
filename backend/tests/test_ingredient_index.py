"""성분 인덱스 캐시 회귀 테스트(2026-07-30 성능 개선).

랭킹 루프가 `product.ingredients`(ORM 관계) 대신 `ingredient_index()` 를 보도록 바꿨다.
같은 데이터를 보고 있는지가 핵심 — 어긋나면 추천 결과가 조용히 달라진다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Brand, Ingredient, Product, ProductIngredient
from app.services.recommender import (
    clear_personal_color_candidate_cache,
    ingredient_index,
)


@pytest.fixture()
def db_session():
    """테스트 전용 인메모리 DB. 공용 픽스처가 없어 이 파일 안에서 만든다."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        clear_personal_color_candidate_cache()


def _seed(db):
    brand = Brand(name="테스트브랜드", description="")
    db.add(brand)
    db.flush()
    niacin = Ingredient(name="Niacinamide", benefit="브라이트닝", targets="pigmentation,pore")
    cica = Ingredient(name="Centella Asiatica", benefit="진정", targets="redness")
    db.add_all([niacin, cica])
    db.flush()
    a = Product(brand_id=brand.id, name="A 세럼", category="serum", price=1000,
                description="", skin_types="all")
    b = Product(brand_id=brand.id, name="B 크림", category="cream", price=2000,
                description="", skin_types="dry")
    c = Product(brand_id=brand.id, name="C 성분없음", category="toner", price=500,
                description="", skin_types="all")
    db.add_all([a, b, c])
    db.flush()
    db.add_all([
        ProductIngredient(product_id=a.id, ingredient_id=niacin.id),
        ProductIngredient(product_id=a.id, ingredient_id=cica.id),
        ProductIngredient(product_id=b.id, ingredient_id=cica.id),
    ])
    db.commit()
    return a, b, c


def test_index_matches_orm_relation(db_session):
    """인덱스의 (성분명, 타깃) 이 ORM 관계에서 직접 뽑은 값과 같아야 한다."""
    clear_personal_color_candidate_cache()
    a, b, c = _seed(db_session)
    index = ingredient_index(db_session)

    for product in (a, b, c):
        names, targets = index.get(product.id, (frozenset(), frozenset()))
        orm_names = {pi.ingredient.name for pi in product.ingredients}
        orm_targets = {
            t for pi in product.ingredients for t in (pi.ingredient.targets or "").split(",") if t
        }
        assert names == orm_names, f"{product.name}: 성분명 불일치"
        assert targets == orm_targets, f"{product.name}: 타깃 불일치"


def test_product_without_ingredients_is_absent(db_session):
    """성분이 없는 상품은 인덱스에 없다 — 호출부는 기본값(빈 집합)으로 받아야 한다."""
    clear_personal_color_candidate_cache()
    _a, _b, c = _seed(db_session)
    index = ingredient_index(db_session)
    names, targets = index.get(c.id, (frozenset(), frozenset()))
    assert names == frozenset() and targets == frozenset()


def test_cache_is_reused_and_clearable(db_session):
    """두 번째 호출은 같은 객체(캐시). clear 후에는 새로 만든다."""
    clear_personal_color_candidate_cache()
    _seed(db_session)
    first = ingredient_index(db_session)
    assert ingredient_index(db_session) is first

    clear_personal_color_candidate_cache()
    assert ingredient_index(db_session) is not first
