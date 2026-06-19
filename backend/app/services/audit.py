"""Audit logging for state-affecting actions on Solution/Product/Release."""
from __future__ import annotations

import psycopg


def record(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    operator: str | None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit (entity_type, entity_id, action, old_value, new_value, operator)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (entity_type, entity_id, action, old_value, new_value, operator),
    )


def list_for(
    conn: psycopg.Connection, *, entity_type: str, entity_id: int
) -> list[dict]:
    """Return the audit trail for one entity, most recent first."""
    return conn.execute(
        """
        SELECT id, entity_type, entity_id, action, old_value, new_value,
               operator, created_at
        FROM audit
        WHERE entity_type = %s AND entity_id = %s
        ORDER BY created_at DESC, id DESC
        """,
        (entity_type, entity_id),
    ).fetchall()
