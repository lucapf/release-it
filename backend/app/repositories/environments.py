"""Environment data access — raw parametrized SQL via psycopg3."""
from __future__ import annotations

import psycopg

_COLS = "id, name, description, created_at"


def create(conn: psycopg.Connection, name: str, description: str) -> dict:
    return conn.execute(
        f"INSERT INTO environment (name, description) VALUES (%s, %s) RETURNING {_COLS}",
        (name, description),
    ).fetchone()


def get(conn: psycopg.Connection, env_id: int) -> dict | None:
    return conn.execute(
        f"SELECT {_COLS} FROM environment WHERE id = %s", (env_id,)
    ).fetchone()


def list_all(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(f"SELECT {_COLS} FROM environment ORDER BY name").fetchall()


def update(conn: psycopg.Connection, env_id: int, name: str, description: str) -> dict | None:
    return conn.execute(
        f"UPDATE environment SET name = %s, description = %s WHERE id = %s RETURNING {_COLS}",
        (name, description, env_id),
    ).fetchone()


def delete(conn: psycopg.Connection, env_id: int) -> bool:
    cur = conn.execute("DELETE FROM environment WHERE id = %s", (env_id,))
    return cur.rowcount > 0
