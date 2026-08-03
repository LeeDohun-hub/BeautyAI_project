"""카탈로그 복사 스크립트(scripts/clone_catalog_to_dev.py) 검증.

운영 DB 를 붙잡고 시험할 수 없어 sqlite↔sqlite 로 같은 코드 경로를 돌린다.
확인하려는 것은 셋이다:
  1. 카탈로그가 FK 순서대로 온전히 옮겨지는가
  2. **개인정보 테이블이 따라가지 않는가** (이 스크립트의 존재 이유)
  3. --target 이 운영이면 거부하는가 (source/target 을 바꿔 넣는 흔한 실수)
"""

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.domain import Brand, Ingredient, Product, ProductIngredient, SkinAnalysis, User

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "clone_catalog_to_dev.py"


@pytest.fixture(scope="module")
def clone_mod():
    spec = importlib.util.spec_from_file_location("clone_catalog_to_dev", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["clone_catalog_to_dev"] = module
    spec.loader.exec_module(module)
    return module


def _session(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_copies_catalog_but_not_personal_data(clone_mod, tmp_path: Path) -> None:
    src = _session(tmp_path / "src.db")
    brand = Brand(name="페리페라")
    ing = Ingredient(name="나이아신아마이드", benefit="미백·피지 조절", targets="pigmentation")
    src.add_all([brand, ing])
    src.commit()
    product = Product(name="잉크 무드 글로이 틴트", brand_id=brand.id, category="lip")
    src.add(product)
    src.commit()
    src.add(ProductIngredient(product_id=product.id, ingredient_id=ing.id))
    # 개인정보 — 따라가면 안 된다
    user = User(email="real@person.com", name="실사용자")
    src.add(user)
    src.commit()
    src.add(SkinAnalysis(user_id=user.id, acne=10, pore=10, wrinkle=10, redness=10, pigmentation=10, oiliness=10))
    src.commit()

    dst = _session(tmp_path / "dst.db")
    for model in clone_mod.CATALOG_TABLES:
        clone_mod._copy_table(src, dst, model)

    assert dst.execute(select(Product)).scalars().one().name == "잉크 무드 글로이 틴트"
    assert len(dst.execute(select(ProductIngredient)).scalars().all()) == 1
    # 핵심: 개발 DB 에 실제 사용자 데이터가 없어야 한다
    assert dst.execute(select(User)).scalars().all() == []
    assert dst.execute(select(SkinAnalysis)).scalars().all() == []


def test_seeded_users_are_fake(clone_mod, tmp_path: Path) -> None:
    dst = _session(tmp_path / "seed.db")
    assert clone_mod._seed_users(dst, 2) == 2
    assert clone_mod._seed_users(dst, 2) == 0, "두 번 돌려도 중복 생성되면 안 된다"
    emails = sorted(u.email for u in dst.execute(select(User)).scalars().all())
    assert emails == ["dev1@example.com", "dev2@example.com"]


def test_refuses_production_target(clone_mod) -> None:
    prod = "postgresql://postgres.ekmelstemgzjbjppoalg:pw@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres"
    with pytest.raises(SystemExit) as exc:
        clone_mod._refuse_if_target_is_production(prod)
    assert "운영" in str(exc.value)
    clone_mod._refuse_if_target_is_production("sqlite:///./dev.db")  # 개발 대상은 통과


def test_password_is_masked_in_logs(clone_mod) -> None:
    masked = clone_mod._mask("postgresql://postgres.abc:s3cr3t@host:5432/postgres")
    assert "s3cr3t" not in masked
    assert masked == "postgresql://postgres.abc:****@host:5432/postgres"
