"""운영 DB 의 **카탈로그만** 개발 DB 로 복사한다.

왜 필요한가
-----------
개발용 DB 를 분리하면(2026-08-03 결정) 로컬이 텅 빈다. 추천·아이템매칭은 상품 7,228건이
없으면 손도 못 대므로, 개발 DB 를 쓸모 있게 만들려면 카탈로그를 옮겨야 한다.

왜 개인정보는 안 옮기는가
-------------------------
**의도적으로 카탈로그만 복사한다.** users·skin_analyses·surveys·recommendation_histories·
chat_histories 는 실제 사용자 데이터다. 개발 DB 는 백업도 접근통제도 운영보다 느슨한데,
거기에 복사하는 순간 개인정보가 관리되지 않는 곳으로 퍼진다.
로그인이 필요하면 --seed-users 로 **가짜 계정**을 만든다.

사용
----
    python scripts/clone_catalog_to_dev.py \
        --source "postgresql://...운영..." \
        --target "postgresql://...개발..." \
        --seed-users 3

    # 운영 URL 은 .env.prod 에서 읽어도 된다
    python scripts/clone_catalog_to_dev.py --source-from-env-file .env.prod --target "..."
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# ⚠️ 임포트 순서 주의: app.core.database 를 먼저 건드리면 로컬 .env 기준으로 엔진이 만들어진다.
#    이 스크립트는 두 URL 을 인자로 받아 **자기 엔진을 따로** 만든다.
os.environ.setdefault("ALLOW_PRODUCTION_DB", "true")  # 운영에서 읽어오는 게 이 스크립트의 목적

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.models.domain import (  # noqa: E402
    Brand,
    Ingredient,
    Product,
    ProductIngredient,
    User,
)

# FK 순서다. 바꾸면 삽입이 깨진다(products 는 brands 를, product_ingredients 는 둘 다 참조).
CATALOG_TABLES = [Brand, Ingredient, Product, ProductIngredient]


def _read_env_file(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip()
    return None


def _mask(url: str) -> str:
    """비밀번호를 지운 채로 로그에 남긴다."""
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:****@{host}"


def _refuse_if_target_is_production(target: str) -> None:
    """개발 DB 를 채우려다 운영을 덮어쓰는 사고를 막는다.

    --source 와 --target 을 바꿔 넣는 실수는 흔하고, 이 스크립트는 지우고 다시 넣는다.
    """
    marker = get_settings().production_db_marker.strip()
    if marker and marker in target:
        raise SystemExit(
            f"거부: --target 이 운영 DB 를 가리킵니다({_mask(target)}).\n"
            "  이 스크립트는 대상 카탈로그를 비우고 다시 채웁니다 — 운영에 쓰면 안 됩니다.\n"
            "  --source 와 --target 을 바꿔 넣지 않았는지 확인하세요."
        )


def _copy_table(src: Session, dst: Session, model: type, batch: int = 1000) -> int:
    columns = [c.name for c in model.__table__.columns]
    rows = src.execute(select(model)).scalars().all()
    for start in range(0, len(rows), batch):
        dst.bulk_insert_mappings(
            model, [{c: getattr(r, c) for c in columns} for r in rows[start : start + batch]]
        )
        dst.commit()
    return len(rows)


def _seed_users(dst: Session, count: int) -> int:
    """개발용 가짜 계정. 실제 사용자 계정은 절대 복사하지 않는다.

    비밀번호는 넣지 않는다 — AI 쪽 User 에는 비밀번호 컬럼이 아예 없다.
    로그인은 BeautyWEB 핸드오프 티켓으로만 들어오고, 여기 행은 그 결과로 생기는 프로필이다.
    """
    made = 0
    for i in range(1, count + 1):
        email = f"dev{i}@example.com"
        if dst.execute(select(User).where(User.email == email)).scalar_one_or_none():
            continue
        dst.add(User(email=email, name=f"개발계정{i}", role="customer"))
        made += 1
    dst.commit()
    return made


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", help="운영 DB URL")
    parser.add_argument("--source-from-env-file", help="DATABASE_URL 을 읽어올 파일(예: .env.prod)")
    parser.add_argument("--target", required=True, help="개발 DB URL")
    parser.add_argument("--seed-users", type=int, default=0, help="개발용 가짜 계정 N개 생성")
    parser.add_argument("--dry-run", action="store_true", help="세지만 쓰지는 않는다")
    args = parser.parse_args()

    source = args.source
    if not source and args.source_from_env_file:
        source = _read_env_file(ROOT / args.source_from_env_file, "DATABASE_URL")
    if not source:
        raise SystemExit("--source 또는 --source-from-env-file 이 필요합니다")

    _refuse_if_target_is_production(args.target)

    print(f"원본: {_mask(source)}")
    print(f"대상: {_mask(args.target)}")

    src_engine = create_engine(source, pool_pre_ping=True)
    dst_engine = create_engine(args.target, pool_pre_ping=True)
    SrcSession = sessionmaker(bind=src_engine, expire_on_commit=False)
    DstSession = sessionmaker(bind=dst_engine, expire_on_commit=False)

    with SrcSession() as src:
        # 세기만 할 때 행을 전부 끌어오면 원거리 리전(시드니)에서 몇 분이 걸린다.
        counts = {
            m.__tablename__: src.execute(select(func.count()).select_from(m)).scalar_one()
            for m in CATALOG_TABLES
        }
    print("원본 카탈로그: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))

    if args.dry_run:
        print("--dry-run: 아무것도 쓰지 않았습니다")
        return

    Base.metadata.create_all(dst_engine)

    with SrcSession() as src, DstSession() as dst:
        # 역순으로 비운다 — FK 를 참조하는 쪽이 먼저 사라져야 한다.
        for model in reversed(CATALOG_TABLES):
            dst.query(model).delete(synchronize_session=False)
        dst.commit()

        for model in CATALOG_TABLES:
            n = _copy_table(src, dst, model)
            print(f"  {model.__tablename__}: {n:,}건 복사")

        if args.seed_users:
            print(f"  users: 개발용 가짜 계정 {_seed_users(dst, args.seed_users)}개 생성 "
                  f"(비밀번호 devpassword1234)")

    print("완료. 개인정보 테이블(users 실계정·분석·설문·추천이력·상담)은 복사하지 않았습니다.")


if __name__ == "__main__":
    main()
