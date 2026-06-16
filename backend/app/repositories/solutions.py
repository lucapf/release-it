"""Solution data access — raw parametrized SQL via psycopg3.

A Solution groups products. Its derived state and the union of pre/post checks
are computed from the *latest* release of each member product.
"""
from __future__ import annotations

import psycopg

_COLS = "id, name, version, created_at"


def create(conn: psycopg.Connection, name: str, version: str) -> dict:
    return conn.execute(
        f"INSERT INTO solution (name, version) VALUES (%s, %s) RETURNING {_COLS}",
        (name, version),
    ).fetchone()


def get(conn: psycopg.Connection, solution_id: int) -> dict | None:
    return conn.execute(
        f"SELECT {_COLS} FROM solution WHERE id = %s", (solution_id,)
    ).fetchone()


def list_all(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(f"SELECT {_COLS} FROM solution ORDER BY name").fetchall()


def latest_release_states(conn: psycopg.Connection, solution_id: int) -> list[dict]:
    """For each product in the solution, the state of its most recent release."""
    return conn.execute(
        """
        SELECT DISTINCT ON (p.id) p.id AS product_id, p.name AS product_name, r.state
        FROM product p
        JOIN release r ON r.product_id = p.id
        WHERE p.solution_id = %s
        ORDER BY p.id, r.created_at DESC
        """,
        (solution_id,),
    ).fetchall()


def union_checks(conn: psycopg.Connection, solution_id: int) -> list[dict]:
    """Union of pre/post checks across the latest release of each member product."""
    return conn.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (p.id) r.id AS release_id
            FROM product p
            JOIN release r ON r.product_id = p.id
            WHERE p.solution_id = %s
            ORDER BY p.id, r.created_at DESC
        )
        SELECT DISTINCT c.label, c.phase
        FROM check_item c
        JOIN latest l ON l.release_id = c.release_id
        ORDER BY c.phase, c.label
        """,
        (solution_id,),
    ).fetchall()
