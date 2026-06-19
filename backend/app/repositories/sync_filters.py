"""Saved per-release tracker sync filter — raw parametrized SQL via psycopg3.

A release remembers the last filter (milestone / label / JQL) an operator chose
to retrieve its issue list, so the Issues tab can re-apply it automatically.
"""
from __future__ import annotations

import psycopg

_COLS = "release_id, filter_mode, filter_value, updated_at"


def get(conn: psycopg.Connection, release_id: int) -> dict | None:
    return conn.execute(
        f"SELECT {_COLS} FROM release_sync_filter WHERE release_id = %s",
        (release_id,),
    ).fetchone()


def upsert(conn: psycopg.Connection, release_id: int, mode: str, value: str) -> dict:
    return conn.execute(
        """
        INSERT INTO release_sync_filter (release_id, filter_mode, filter_value, updated_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (release_id) DO UPDATE
            SET filter_mode  = EXCLUDED.filter_mode,
                filter_value = EXCLUDED.filter_value,
                updated_at   = now()
        RETURNING {cols}
        """.format(cols=_COLS),
        (release_id, mode, value),
    ).fetchone()
