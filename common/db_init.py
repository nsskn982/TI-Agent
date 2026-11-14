"""Create or upgrade the local database schema (db/schema.sql is idempotent).

    python -m common.db_init

Needs PostgreSQL 15+ with the pgvector extension, reachable at DATABASE_URL
(default: the Docker container from docker-compose.yml).
"""
from __future__ import annotations

import sys

from common.config import ROOT
from common.store import database_url


def main() -> int:
    import psycopg

    sql = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    try:
        with psycopg.connect(database_url(), autocommit=True) as conn:
            conn.execute(sql)
    except psycopg.OperationalError as exc:
        print(f"Could not connect to PostgreSQL ({exc}).\nStart it with: docker compose up -d", file=sys.stderr)
        return 2
    print("Schema is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
