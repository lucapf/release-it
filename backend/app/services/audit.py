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
