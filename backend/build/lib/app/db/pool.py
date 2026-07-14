"""psycopg3 connection pool, shared across the app.

The pool is opened on FastAPI startup (lifespan) and closed on shutdown.
Repositories acquire a connection per request via the ``get_conn`` dependency.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import settings

_pool: ConnectionPool | None = None


def open_pool() -> None:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=True,
        )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("Connection pool is not open. Call open_pool() first.")
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """Yield a pooled connection, committing on success and rolling back on error."""
    with get_pool().connection() as conn:
        yield conn


# FastAPI dependency
def get_conn() -> Iterator[psycopg.Connection]:
    with connection() as conn:
        yield conn
