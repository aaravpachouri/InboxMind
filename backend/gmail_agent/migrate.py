from __future__ import annotations

import os
from pathlib import Path

import psycopg


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required before running database migrations.")
    migration = Path(__file__).resolve().parent.parent / "migrations" / "0001_multi_tenant_schema.sql"
    sql = migration.read_text(encoding="utf-8")
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(sql)
    print(f"Applied {migration.name}")


if __name__ == "__main__":
    main()
