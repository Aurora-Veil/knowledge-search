"""Apply schema/auth.sql to the database in PG_DSN."""

from __future__ import annotations

import sys
from pathlib import Path

# repo root on sys.path, so this runs from any working directory
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from app.config import pg_dsn  # noqa: E402

SCHEMA = ROOT / "schema" / "auth.sql"
TABLES = ("users", "search_history", "search_log")


def apply_schema() -> None:
    with psycopg.connect(pg_dsn(), connect_timeout=5) as conn:   # commits on exit
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
    print(f"applied {SCHEMA.relative_to(ROOT)}")


def summary() -> None:
    with psycopg.connect(pg_dsn(), connect_timeout=5) as conn:
        for table in TABLES:
            n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"  {table:<16} {n:>6} rows")
        print("  indexes")
        for (name,) in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
            " ORDER BY indexname"
        ):
            print(f"    {name}")


def main() -> None:
    apply_schema()
    summary()


if __name__ == "__main__":
    main()
