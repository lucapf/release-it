"""psycopg3 pool + plain-SQL migration runner for releaseit-auth."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import sqlparse
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

_pool: ConnectionPool | None = None

_ENSURE_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def open_pool() -> None:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            kwargs={"row_factory": dict_row},
            open=True,
        )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    if _pool is None:
        raise RuntimeError("pool not open")
    with _pool.connection() as conn:
        yield conn


def get_conn() -> Iterator[psycopg.Connection]:
    with connection() as conn:
        yield conn


def apply_migrations() -> list[str]:
    migrations_dir = Path(__file__).resolve().parents[1] / settings.migrations_dir
    applied: list[str] = []
    with connection() as conn:
        conn.execute(_ENSURE_MIGRATIONS)
        done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        for path in sorted(migrations_dir.glob("*.sql"), key=lambda p: p.name):
            if path.stem in done:
                continue
            for stmt in sqlparse.split(path.read_text(encoding="utf-8")):
                if stmt.strip():
                    conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            applied.append(path.stem)
        conn.commit()
    return applied
