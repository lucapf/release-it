"""Files staged from the chat, awaiting the assistant linking them to a document.

The chat transcript is text-only, so a file the operator attaches is uploaded
here first (POST /api/v1/chat/attachments) and only its metadata is shown to the
model. When the model links it, the bytes are copied into a document version and
the row is marked linked — see ``migrations/0019_chat_attachment.sql``.
"""
from __future__ import annotations

import psycopg

# How long an unlinked attachment is kept before it is purged. Long enough for a
# conversation ("upload this, now which release is it for?"), short enough that
# files the operator never linked do not accumulate.
TTL_HOURS = 24

# Metadata only — never the content, which is loaded on demand by `content_of`.
_META = "id, filename, content_type, size, uploaded_by, created_at, linked_document_id, linked_at"


def create(
    conn: psycopg.Connection,
    filename: str,
    content_type: str,
    content: bytes,
    uploaded_by: str | None,
) -> dict:
    """Stage an uploaded file and return its metadata."""
    return conn.execute(
        f"""
        INSERT INTO chat_attachment (filename, content_type, content, size, uploaded_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING {_META}
        """,
        (filename, content_type, content, len(content), uploaded_by),
    ).fetchone()


def get(conn: psycopg.Connection, attachment_id: int) -> dict | None:
    """One attachment's metadata (no content)."""
    return conn.execute(
        f"SELECT {_META} FROM chat_attachment WHERE id = %s", (attachment_id,)
    ).fetchone()


def content_of(conn: psycopg.Connection, attachment_id: int) -> bytes | None:
    row = conn.execute(
        "SELECT content FROM chat_attachment WHERE id = %s", (attachment_id,)
    ).fetchone()
    return bytes(row["content"]) if row else None


def pending(
    conn: psycopg.Connection, ids: list[int], uploaded_by: str | None
) -> list[dict]:
    """Of the attachments the client says are in play, those that belong to this
    operator and are not yet linked — the ones to put in front of the model."""
    if not ids:
        return []
    return conn.execute(
        f"""
        SELECT {_META} FROM chat_attachment
        WHERE id = ANY(%s) AND uploaded_by IS NOT DISTINCT FROM %s AND linked_at IS NULL
        ORDER BY created_at, id
        """,
        (list(ids), uploaded_by),
    ).fetchall()


def linked_ids(conn: psycopg.Connection, ids: list[int]) -> list[int]:
    """Which of these attachments are now linked to a document — the chat reports
    them back so the UI can drop them from the composer."""
    if not ids:
        return []
    rows = conn.execute(
        "SELECT id FROM chat_attachment WHERE id = ANY(%s) AND linked_at IS NOT NULL",
        (list(ids),),
    ).fetchall()
    return [r["id"] for r in rows]


def mark_linked(conn: psycopg.Connection, attachment_id: int, document_id: int) -> dict | None:
    """Spend the attachment: record the document it became part of. The WHERE
    clause makes this a no-op on an already-linked row, so a double link attempt
    is caught by the caller (which checks for None) rather than duplicating a
    version."""
    return conn.execute(
        f"""
        UPDATE chat_attachment
           SET linked_document_id = %s, linked_at = now()
         WHERE id = %s AND linked_at IS NULL
        RETURNING {_META}
        """,
        (document_id, attachment_id),
    ).fetchone()


def purge_stale(conn: psycopg.Connection, ttl_hours: int = TTL_HOURS) -> int:
    """Drop unlinked attachments older than the TTL. Called on upload, so the
    staging table stays bounded without a scheduled job."""
    rows = conn.execute(
        """
        DELETE FROM chat_attachment
         WHERE linked_at IS NULL
           AND created_at < now() - make_interval(hours => %s)
        RETURNING id
        """,
        (ttl_hours,),
    ).fetchall()
    return len(rows)
