"""Runtime configuration + check-template data access — raw SQL via psycopg3."""
from __future__ import annotations

import psycopg


# --- app_config key/value store --------------------------------------------
def get_all(conn: psycopg.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM app_config").fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_many(conn: psycopg.Connection, values: dict[str, str]) -> None:
    """Upsert a batch of config keys. Keys absent from ``values`` are untouched."""
    for key, value in values.items():
        conn.execute(
            """
            INSERT INTO app_config (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = now()
            """,
            (key, value),
        )


# --- check_template (global default checks) --------------------------------
def list_check_templates(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "SELECT id, label, phase, created_at FROM check_template ORDER BY phase, id"
    ).fetchall()


def add_check_template(conn: psycopg.Connection, label: str, phase: str) -> dict:
    return conn.execute(
        """
        INSERT INTO check_template (label, phase) VALUES (%s, %s)
        RETURNING id, label, phase, created_at
        """,
        (label, phase),
    ).fetchone()


def delete_check_template(conn: psycopg.Connection, template_id: int) -> bool:
    cur = conn.execute("DELETE FROM check_template WHERE id = %s", (template_id,))
    return cur.rowcount > 0


# --- document_type (admin-managed supported document types) -----------------
def list_document_types(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "SELECT id, name, created_at FROM document_type ORDER BY name"
    ).fetchall()


def document_type_names(conn: psycopg.Connection) -> set[str]:
    """The set of configured type names, for validating uploads."""
    rows = conn.execute("SELECT name FROM document_type").fetchall()
    return {r["name"] for r in rows}


def add_document_type(conn: psycopg.Connection, name: str) -> dict:
    return conn.execute(
        """
        INSERT INTO document_type (name) VALUES (%s)
        RETURNING id, name, created_at
        """,
        (name,),
    ).fetchone()


def delete_document_type(conn: psycopg.Connection, type_id: int) -> bool:
    cur = conn.execute("DELETE FROM document_type WHERE id = %s", (type_id,))
    return cur.rowcount > 0
