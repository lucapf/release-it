"""Release data access (releases, checks, artifacts, docs) — raw SQL via psycopg3."""
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


def set_state(conn: psycopg.Connection, release_id: int, state: str) -> dict | None:
    return conn.execute(
        f"UPDATE release SET state = %s WHERE id = %s RETURNING {_REL_COLS}",
        (state, release_id),
    ).fetchone()


# --- Checks ----------------------------------------------------------------
def add_check(conn: psycopg.Connection, release_id: int, label: str, phase: str) -> dict:
    return conn.execute(
        """
        INSERT INTO check_item (release_id, label, phase)
        VALUES (%s, %s, %s)
        RETURNING id, release_id, label, phase, done, created_at
        """,
        (release_id, label, phase),
    ).fetchone()


def list_checks(conn: psycopg.Connection, release_id: int) -> list[dict]:
    return conn.execute(
        """
        SELECT id, release_id, label, phase, done, created_at
        FROM check_item WHERE release_id = %s ORDER BY phase, id
        """,
        (release_id,),
    ).fetchall()


def set_check_done(conn: psycopg.Connection, check_id: int, done: bool) -> dict | None:
    return conn.execute(
        """
        UPDATE check_item SET done = %s WHERE id = %s
        RETURNING id, release_id, label, phase, done, created_at
        """,
        (done, check_id),
    ).fetchone()


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


# --- Documentation (bytea) -------------------------------------------------
def add_documentation(
    conn: psycopg.Connection,
    release_id: int,
    name: str,
    content_type: str,
    content: bytes,
    is_draft: bool,
) -> dict:
    return conn.execute(
        """
        INSERT INTO documentation (release_id, name, content_type, content, is_draft)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, release_id, name, content_type, is_draft, created_at
        """,
        (release_id, name, content_type, content, is_draft),
    ).fetchone()


def list_documentation(conn: psycopg.Connection, release_id: int) -> list[dict]:
    return conn.execute(
        """
        SELECT id, release_id, name, content_type, is_draft, created_at
        FROM documentation WHERE release_id = %s ORDER BY id
        """,
        (release_id,),
    ).fetchall()


# --- Inheritance: clone assets of a rejected release into a new one ---------
def clone_assets(conn: psycopg.Connection, source_id: int, target_id: int) -> None:
    """Copy checks, artifacts and documentation from source release to target."""
    conn.execute(
        """
        INSERT INTO check_item (release_id, label, phase, done)
        SELECT %s, label, phase, false FROM check_item WHERE release_id = %s
        """,
        (target_id, source_id),
    )
    conn.execute(
        """
        INSERT INTO artifact (release_id, name, content_type, content)
        SELECT %s, name, content_type, content FROM artifact WHERE release_id = %s
        """,
        (target_id, source_id),
    )
    conn.execute(
        """
        INSERT INTO documentation (release_id, name, content_type, content, is_draft)
        SELECT %s, name, content_type, content, is_draft
        FROM documentation WHERE release_id = %s
        """,
        (target_id, source_id),
    )
