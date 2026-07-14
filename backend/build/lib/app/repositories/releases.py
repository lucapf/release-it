"""Release data access (releases, artifacts, docs) — raw SQL via psycopg3."""
from __future__ import annotations

import psycopg

_REL_COLS = (
    "id, product_id, version, state, short_description, parent_release_id, created_at"
)


# --- Releases --------------------------------------------------------------
def create(
    conn: psycopg.Connection,
    *,
    product_id: int,
    version: str,
    state: str,
    short_description: str,
    parent_release_id: int | None = None,
) -> dict:
    return conn.execute(
        f"""
        INSERT INTO release (product_id, version, state, short_description, parent_release_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING {_REL_COLS}
        """,
        (product_id, version, state, short_description, parent_release_id),
    ).fetchone()


def get(conn: psycopg.Connection, release_id: int) -> dict | None:
    return conn.execute(
        f"SELECT {_REL_COLS} FROM release WHERE id = %s", (release_id,)
    ).fetchone()


def list_by_product(conn: psycopg.Connection, product_id: int) -> list[dict]:
    return conn.execute(
        f"SELECT {_REL_COLS} FROM release WHERE product_id = %s ORDER BY created_at DESC",
        (product_id,),
    ).fetchall()


def list_all(conn: psycopg.Connection) -> list[dict]:
    """Every release across all products (newest first per product). Used by the
    assistant to build a cross-product status report."""
    return conn.execute(
        f"SELECT {_REL_COLS} FROM release ORDER BY product_id, created_at DESC"
    ).fetchall()


# A cancelled or rejected release never shipped — its tag may not even exist —
# so it cannot serve as the baseline a code diff is taken against. State names
# match the seeded workflow, like the dashboard constants in products.py.
_DEAD_STATES = ["Cancelled", "Rejected"]


def previous_release(conn: psycopg.Connection, release_id: int) -> dict | None:
    """The most recent prior release of the same product (by creation time),
    skipping cancelled/rejected ones. None for a product's first release."""
    return conn.execute(
        f"""
        SELECT {_REL_COLS} FROM release
        WHERE product_id = (SELECT product_id FROM release WHERE id = %s)
          AND created_at < (SELECT created_at FROM release WHERE id = %s)
          AND state <> ALL(%s)
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (release_id, release_id, _DEAD_STATES),
    ).fetchone()


def set_state(conn: psycopg.Connection, release_id: int, state: str) -> dict | None:
    return conn.execute(
        f"UPDATE release SET state = %s WHERE id = %s RETURNING {_REL_COLS}",
        (state, release_id),
    ).fetchone()


def delete(conn: psycopg.Connection, release_id: int) -> bool:
    """Delete a release. Child rows (artifacts, documents, synced issues,
    sync filter) cascade via their FKs; inherited releases keep their
    history with parent_release_id reset to NULL."""
    cur = conn.execute("DELETE FROM release WHERE id = %s", (release_id,))
    return cur.rowcount > 0


# --- Artifacts (bytea) -----------------------------------------------------
def add_artifact(
    conn: psycopg.Connection, release_id: int, name: str, content_type: str, content: bytes
) -> dict:
    return conn.execute(
        """
        INSERT INTO artifact (release_id, name, content_type, content)
        VALUES (%s, %s, %s, %s)
        RETURNING id, release_id, name, content_type, created_at
        """,
        (release_id, name, content_type, content),
    ).fetchone()


def list_artifacts(conn: psycopg.Connection, release_id: int) -> list[dict]:
    return conn.execute(
        """
        SELECT id, release_id, name, content_type, created_at
        FROM artifact WHERE release_id = %s ORDER BY id
        """,
        (release_id,),
    ).fetchall()


def get_artifact_content(conn: psycopg.Connection, artifact_id: int) -> dict | None:
    return conn.execute(
        "SELECT name, content_type, content FROM artifact WHERE id = %s", (artifact_id,)
    ).fetchone()


# --- Inheritance: clone assets of a rejected release into a new one ---------
def clone_assets(conn: psycopg.Connection, source_id: int, target_id: int) -> None:
    """Copy artifacts from source release to target."""
    conn.execute(
        """
        INSERT INTO artifact (release_id, name, content_type, content)
        SELECT %s, name, content_type, content FROM artifact WHERE release_id = %s
        """,
        (target_id, source_id),
    )
