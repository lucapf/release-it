"""Product data access — raw parametrized SQL via psycopg3."""
from __future__ import annotations

import psycopg


def create(conn: psycopg.Connection, name: str, solution_id: int | None) -> dict:
    return conn.execute(
        """
        INSERT INTO product (name, solution_id)
        VALUES (%s, %s)
        RETURNING id, name, solution_id, created_at
        """,
        (name, solution_id),
    ).fetchone()


def get(conn: psycopg.Connection, product_id: int) -> dict | None:
    return conn.execute(
        "SELECT id, name, solution_id, created_at FROM product WHERE id = %s",
        (product_id,),
    ).fetchone()


def list_all(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "SELECT id, name, solution_id, created_at FROM product ORDER BY name"
    ).fetchall()


# Dashboard states. Matches states.yaml: a release awaiting approval sits in
# 'In QA' (the state reached by the 'Ready' transition out of 'Draft').
_DRAFT_STATE = "Draft"
_APPROVAL_STATE = "In QA"
_REL_COLS = (
    "id, product_id, version, state, short_description, parent_release_id, created_at"
)


def overview(conn: psycopg.Connection) -> list[dict]:
    """Per-product dashboard data: the latest draft and the latest under-approval
    release, plus a total release count — in a single round-trip.

    The draft / under-approval releases are returned as nested JSON objects
    (``to_jsonb``) so they map straight onto the ``Release`` pydantic model.
    """
    return conn.execute(
        f"""
        SELECT
            p.id, p.name, p.solution_id, p.created_at,
            (SELECT count(*) FROM release WHERE product_id = p.id) AS release_count,
            (
                SELECT to_jsonb(d) FROM (
                    SELECT {_REL_COLS} FROM release
                    WHERE product_id = p.id AND state = %(draft)s
                    ORDER BY created_at DESC LIMIT 1
                ) d
            ) AS draft,
            (
                SELECT to_jsonb(a) FROM (
                    SELECT {_REL_COLS} FROM release
                    WHERE product_id = p.id AND state = %(approval)s
                    ORDER BY created_at DESC LIMIT 1
                ) a
            ) AS under_approval
        FROM product p
        ORDER BY p.name
        """,
        {"draft": _DRAFT_STATE, "approval": _APPROVAL_STATE},
    ).fetchall()


def delete(conn: psycopg.Connection, product_id: int) -> bool:
    cur = conn.execute("DELETE FROM product WHERE id = %s", (product_id,))
    return cur.rowcount > 0
