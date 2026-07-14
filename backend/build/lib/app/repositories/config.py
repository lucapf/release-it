"""Runtime configuration data access — raw SQL via psycopg3."""
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


# --- document_type (admin-managed supported document types) -----------------
_DOC_TYPE_COLS = "id, name, kind, generation_prompt, created_at"


def list_document_types(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        f"SELECT {_DOC_TYPE_COLS} FROM document_type ORDER BY name"
    ).fetchall()


def get_document_type(conn: psycopg.Connection, type_id: int) -> dict | None:
    return conn.execute(
        f"SELECT {_DOC_TYPE_COLS} FROM document_type WHERE id = %s", (type_id,)
    ).fetchone()


def get_document_type_by_name(conn: psycopg.Connection, name: str) -> dict | None:
    """Look up a document type by name (case-insensitive), so callers can resolve a
    type the operator referred to by name."""
    return conn.execute(
        f"SELECT {_DOC_TYPE_COLS} FROM document_type WHERE lower(name) = lower(%s)",
        (name.strip(),),
    ).fetchone()


def document_type_names(conn: psycopg.Connection) -> set[str]:
    """The set of configured type names, for validating uploads."""
    rows = conn.execute("SELECT name FROM document_type").fetchall()
    return {r["name"] for r in rows}


def add_document_type(
    conn: psycopg.Connection, name: str, kind: str = "manual", generation_prompt: str = ""
) -> dict:
    return conn.execute(
        f"""
        INSERT INTO document_type (name, kind, generation_prompt) VALUES (%s, %s, %s)
        RETURNING {_DOC_TYPE_COLS}
        """,
        (name, kind, generation_prompt),
    ).fetchone()


def update_document_type(
    conn: psycopg.Connection,
    type_id: int,
    *,
    name: str | None = None,
    kind: str | None = None,
    generation_prompt: str | None = None,
) -> dict | None:
    """Partial update: only the supplied fields change. Returns the updated row,
    or None when no such type exists."""
    sets: list[str] = []
    params: list = []
    if name is not None:
        sets.append("name = %s")
        params.append(name)
    if kind is not None:
        sets.append("kind = %s")
        params.append(kind)
    if generation_prompt is not None:
        sets.append("generation_prompt = %s")
        params.append(generation_prompt)
    if not sets:
        return get_document_type(conn, type_id)
    params.append(type_id)
    return conn.execute(
        f"UPDATE document_type SET {', '.join(sets)} WHERE id = %s RETURNING {_DOC_TYPE_COLS}",
        tuple(params),
    ).fetchone()


def delete_document_type(conn: psycopg.Connection, type_id: int) -> bool:
    cur = conn.execute("DELETE FROM document_type WHERE id = %s", (type_id,))
    return cur.rowcount > 0
