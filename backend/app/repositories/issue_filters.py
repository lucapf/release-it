"""A release's issue search criteria — raw parametrized SQL via psycopg3.

The criteria (milestone / label / JQL) is what says *which tickets belong to this
release*; an operator chooses it when the release is created. It is the only thing
Release-It stores about a release's issues — the tickets themselves are read from
the ticketing system on every query, never copied into this database.
"""
from __future__ import annotations

import psycopg

_COLS = "release_id, filter_mode, filter_value, updated_at"


def get(conn: psycopg.Connection, release_id: int) -> dict | None:
    return conn.execute(
        f"SELECT {_COLS} FROM release_issue_filter WHERE release_id = %s",
        (release_id,),
    ).fetchone()


def upsert(conn: psycopg.Connection, release_id: int, mode: str, value: str) -> dict:
    return conn.execute(
        """
        INSERT INTO release_issue_filter (release_id, filter_mode, filter_value, updated_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (release_id) DO UPDATE
            SET filter_mode  = EXCLUDED.filter_mode,
                filter_value = EXCLUDED.filter_value,
                updated_at   = now()
        RETURNING {cols}
        """.format(cols=_COLS),
        (release_id, mode, value),
    ).fetchone()


def copy(conn: psycopg.Connection, source_id: int, target_id: int) -> None:
    """Give ``target_id`` the criteria of ``source_id`` (no-op when it has none).

    An inherited release contains the same work as the release it inherits from,
    so it inherits the criteria that defines that work along with the assets.
    """
    conn.execute(
        """
        INSERT INTO release_issue_filter (release_id, filter_mode, filter_value)
        SELECT %s, filter_mode, filter_value
        FROM release_issue_filter WHERE release_id = %s
        ON CONFLICT (release_id) DO UPDATE
            SET filter_mode  = EXCLUDED.filter_mode,
                filter_value = EXCLUDED.filter_value,
                updated_at   = now()
        """,
        (target_id, source_id),
    )
