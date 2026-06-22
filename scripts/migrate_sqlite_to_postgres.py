"""Copy all data from the local SQLite DB into a Postgres/Supabase database.

Usage (run schema migration on the target FIRST, then copy data):

    # 1) point .env DATABASE_URL at Supabase, create the schema there:
    cd backend && .venv/Scripts/python.exe -m alembic upgrade head

    # 2) copy rows from the old sqlite file into the target:
    backend/.venv/Scripts/python.exe scripts/migrate_sqlite_to_postgres.py \
        --source sqlite:///./beautyai.db \
        --target "postgresql+psycopg2://postgres:PASSWORD@HOST:5432/postgres"

If --target is omitted it falls back to the TARGET_DATABASE_URL env var, then to
the app's DATABASE_URL setting. The script copies tables in FK-dependency order
and, for Postgres targets, resets identity sequences so future inserts don't
collide with the copied primary keys.

The target is assumed to already have the schema (via `alembic upgrade head`).
By default the copy aborts if any target table already has rows; pass --truncate
to wipe target tables first.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make the backend `app` package importable.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, func, select, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base, resolve_database_url  # noqa: E402
from app.models import domain  # noqa: F401,E402  (registers tables on Base.metadata)


def make_engine(url: str):
    url = resolve_database_url(url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="sqlite:///./beautyai.db", help="source SQLAlchemy URL (the old sqlite DB)")
    parser.add_argument("--target", default=None, help="target SQLAlchemy URL (Supabase/Postgres); falls back to TARGET_DATABASE_URL or app DATABASE_URL")
    parser.add_argument("--truncate", action="store_true", help="wipe target tables before copying instead of aborting when non-empty")
    parser.add_argument("--batch", type=int, default=1000, help="insert batch size")
    args = parser.parse_args()

    target_url = args.target or os.environ.get("TARGET_DATABASE_URL") or get_settings().database_url
    source_engine = make_engine(args.source)
    target_engine = make_engine(target_url)
    is_pg = target_engine.dialect.name == "postgresql"

    print(f"Source : {source_engine.url}")
    print(f"Target : {target_engine.url}  (dialect={target_engine.dialect.name})")

    tables = list(Base.metadata.sorted_tables)  # parents before children (FK-safe)

    with source_engine.connect() as src, target_engine.begin() as dst:
        # Guard / optional truncate. Children first for truncate (reverse FK order).
        for table in reversed(tables):
            count = dst.execute(select(func.count()).select_from(table)).scalar_one()
            if count and not args.truncate:
                print(f"ABORT: target table '{table.name}' already has {count} rows. Re-run with --truncate to overwrite.")
                return 1
            if count and args.truncate:
                dst.execute(table.delete())
                print(f"  truncated {table.name} ({count} rows)")

        total = 0
        for table in tables:
            rows = [dict(r._mapping) for r in src.execute(select(table))]
            if not rows:
                print(f"  {table.name}: 0 rows")
                continue
            for i in range(0, len(rows), args.batch):
                dst.execute(table.insert(), rows[i : i + args.batch])
            total += len(rows)
            print(f"  {table.name}: {len(rows)} rows")

        # Postgres: advance identity sequences past the copied explicit ids.
        if is_pg:
            for table in tables:
                if "id" not in table.c:
                    continue
                dst.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence(:t, 'id'), "
                        "COALESCE((SELECT MAX(id) FROM " + table.name + "), 1), true)"
                    ),
                    {"t": table.name},
                )
            print("  reset Postgres id sequences")

    print(f"Done. Copied {total} rows across {len(tables)} tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
