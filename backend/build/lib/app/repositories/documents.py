"""Document management data access — versioned, release-scoped documents.

A ``document`` is a named file on a release; each upload is a ``document_version``
row. Content (bytea) is stored in-DB like artifacts/documentation. Raw SQL via
psycopg3.
"""
from __future__ import annotations

import psycopg

# Document row joined with its latest version, plus a version count. Used for the
# release's document list (one entry per document, showing its current version).
_DOC_LIST_SQL = """
    SELECT d.id, d.release_id, d.title, d.doc_type, d.status, d.created_at,
           v.id           AS latest_version_id,
           v.version      AS latest_version,
           v.filename     AS latest_filename,
           v.content_type AS latest_content_type,
           v.size         AS latest_size,
           v.pdf_size     AS latest_pdf_size,
           v.uploaded_by  AS latest_uploaded_by,
           v.created_at   AS updated_at,
           (SELECT count(*) FROM document_version WHERE document_id = d.id) AS version_count
    FROM document d
    LEFT JOIN LATERAL (
        SELECT id, version, filename, content_type, size, pdf_size, uploaded_by, created_at
        FROM document_version
        WHERE document_id = d.id
        ORDER BY version DESC
        LIMIT 1
    ) v ON true
"""


def create_document(
    conn: psycopg.Connection, release_id: int, title: str, doc_type: str
) -> dict:
    """Create a logical document on a release (no version yet). The document type
    is fixed at creation and shared by every version uploaded afterwards."""
    return conn.execute(
        """
        INSERT INTO document (release_id, title, doc_type)
        VALUES (%s, %s, %s)
        RETURNING id, release_id, title, doc_type, created_at
        """,
        (release_id, title, doc_type),
    ).fetchone()


def get_document(conn: psycopg.Connection, document_id: int) -> dict | None:
    return conn.execute(
        "SELECT id, release_id, title, doc_type, status, created_at FROM document WHERE id = %s",
        (document_id,),
    ).fetchone()


def find_document(conn: psycopg.Connection, release_id: int, title: str) -> dict | None:
    return conn.execute(
        "SELECT id, release_id, title, created_at FROM document WHERE release_id = %s AND title = %s",
        (release_id, title),
    ).fetchone()


def present_types(conn: psycopg.Connection, release_id: int) -> set[str]:
    """The set of document types that have at least one document on the release,
    whatever its status. Display only — a `document:<type>` readiness guard is
    satisfied by `approved_types`, not by this."""
    rows = conn.execute(
        "SELECT DISTINCT doc_type FROM document WHERE release_id = %s",
        (release_id,),
    ).fetchall()
    return {r["doc_type"] for r in rows}


def approved_types(conn: psycopg.Connection, release_id: int) -> set[str]:
    """The set of document types that have at least one APPROVED document on the
    release. A ``document:<type>`` readiness guard requires the document to be
    both attached and approved, so a DRAFT document does not satisfy it."""
    rows = conn.execute(
        "SELECT DISTINCT doc_type FROM document WHERE release_id = %s AND status = 'APPROVED'",
        (release_id,),
    ).fetchall()
    return {r["doc_type"] for r in rows}


def list_documents(conn: psycopg.Connection, release_id: int) -> list[dict]:
    """Every document on a release, each carrying its latest-version metadata."""
    return conn.execute(
        _DOC_LIST_SQL + " WHERE d.release_id = %s ORDER BY d.title, d.id",
        (release_id,),
    ).fetchall()


def get_document_meta(conn: psycopg.Connection, document_id: int) -> dict | None:
    """A single document with its latest-version metadata (same shape as the list)."""
    return conn.execute(
        _DOC_LIST_SQL + " WHERE d.id = %s",
        (document_id,),
    ).fetchone()


def add_version(
    conn: psycopg.Connection,
    document_id: int,
    filename: str,
    content_type: str,
    content: bytes,
    uploaded_by: str | None,
    pdf_content: bytes | None = None,
) -> dict:
    """Append a new version to a document. The version number is the next
    integer after the document's current highest (1 for the first upload).

    ``pdf_content`` is the rendered-PDF companion (for Markdown sources); when
    absent the version keeps only its original bytes. Adding a version returns
    the document to DRAFT — the content it may have been approved on has changed
    and needs re-approval."""
    next_version = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM document_version WHERE document_id = %s",
        (document_id,),
    ).fetchone()["v"]
    row = conn.execute(
        """
        INSERT INTO document_version
            (document_id, version, filename, content_type, content, size,
             pdf_content, pdf_size, uploaded_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, document_id, version, filename, content_type, size,
                  pdf_size, uploaded_by, created_at
        """,
        (document_id, next_version, filename, content_type, content, len(content),
         pdf_content, len(pdf_content) if pdf_content else 0, uploaded_by),
    ).fetchone()
    conn.execute("UPDATE document SET status = 'DRAFT' WHERE id = %s", (document_id,))
    return row


def set_status(conn: psycopg.Connection, document_id: int, status: str) -> dict | None:
    """Set a document's approval status (DRAFT/APPROVED) and return its metadata."""
    updated = conn.execute(
        "UPDATE document SET status = %s WHERE id = %s RETURNING id",
        (status, document_id),
    ).fetchone()
    if updated is None:
        return None
    return get_document_meta(conn, document_id)


def list_versions(conn: psycopg.Connection, document_id: int) -> list[dict]:
    """All versions of a document, newest first."""
    return conn.execute(
        """
        SELECT id, document_id, version, filename, content_type, size, pdf_size,
               uploaded_by, created_at
        FROM document_version
        WHERE document_id = %s
        ORDER BY version DESC
        """,
        (document_id,),
    ).fetchall()


def get_version_content(conn: psycopg.Connection, version_id: int) -> dict | None:
    """Fetch a single version's bytes for download, including its rendered-PDF
    companion (``pdf_content``) when one exists."""
    return conn.execute(
        """
        SELECT dv.id, dv.document_id, dv.filename, dv.content_type, dv.content,
               dv.pdf_content, dv.pdf_size
        FROM document_version dv
        WHERE dv.id = %s
        """,
        (version_id,),
    ).fetchone()


def delete_document(conn: psycopg.Connection, document_id: int) -> bool:
    """Delete a document and all of its versions (cascade)."""
    cur = conn.execute("DELETE FROM document WHERE id = %s", (document_id,))
    return cur.rowcount > 0
