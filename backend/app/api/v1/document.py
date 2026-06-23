"""/api/v1/release/{release_id}/documents — versioned document management.

Operators upload documents to a release; each upload is a new version. Every
previous version stays downloadable. Content is stored in-DB as bytea, like
artifacts and release documentation.
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.jwt_verify import (
    ROLE_ADMIN,
    ROLE_DEVELOPER,
    ROLE_RELEASE_MANAGER,
    Principal,
    require_role,
)
from app.db.pool import get_conn
from app.repositories import config as config_repo
from app.repositories import documents as repo
from app.repositories import releases as releases_repo
from app.schemas.models import DocumentMeta, DocumentVersionMeta

router = APIRouter()

# Who may upload / change documents (reads are open to any authenticated user).
_can_write = require_role(ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_ADMIN)


def _require_release(conn: psycopg.Connection, release_id: int) -> dict:
    rel = releases_repo.get(conn, release_id)
    if rel is None:
        raise HTTPException(404, "Release not found")
    return rel


def _require_document(conn: psycopg.Connection, release_id: int, document_id: int) -> dict:
    doc = repo.get_document(conn, document_id)
    if doc is None or doc["release_id"] != release_id:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("/{release_id}/documents", response_model=list[DocumentMeta])
def list_documents(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    _require_release(conn, release_id)
    return repo.list_documents(conn, release_id)


@router.post("/{release_id}/documents", response_model=DocumentMeta, status_code=201)
async def upload_document(
    release_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    title: str | None = Form(default=None),
    principal: Principal = Depends(_can_write),
    conn: psycopg.Connection = Depends(get_conn),
):
    """Create a new document on the release and store its first version. The
    operator marks it with a supported document type (one of the admin-configured
    types, fixed for all versions). The title defaults to the uploaded file name;
    uploading with the title of an existing document is rejected (use the
    add-version endpoint instead)."""
    _require_release(conn, release_id)
    doc_type = doc_type.strip()
    if doc_type not in config_repo.document_type_names(conn):
        raise HTTPException(400, f'Unsupported document type "{doc_type}"')
    doc_title = (title or file.filename or "document").strip() or "document"
    if repo.find_document(conn, release_id, doc_title) is not None:
        raise HTTPException(
            409, f'A document titled "{doc_title}" already exists; upload a new version instead'
        )
    content = await file.read()
    doc = repo.create_document(conn, release_id, doc_title, doc_type)
    repo.add_version(
        conn,
        doc["id"],
        file.filename or doc_title,
        file.content_type or "application/octet-stream",
        content,
        principal.subject or None,
    )
    return repo.get_document_meta(conn, doc["id"])


@router.get("/{release_id}/documents/{document_id}/versions", response_model=list[DocumentVersionMeta])
def list_versions(
    release_id: int, document_id: int, conn: psycopg.Connection = Depends(get_conn)
):
    _require_release(conn, release_id)
    _require_document(conn, release_id, document_id)
    return repo.list_versions(conn, document_id)


@router.post(
    "/{release_id}/documents/{document_id}/versions",
    response_model=DocumentMeta,
    status_code=201,
)
async def upload_version(
    release_id: int,
    document_id: int,
    file: UploadFile = File(...),
    principal: Principal = Depends(_can_write),
    conn: psycopg.Connection = Depends(get_conn),
):
    """Upload a new version of an existing document. The version number is
    assigned automatically; the previous versions remain downloadable."""
    _require_release(conn, release_id)
    doc = _require_document(conn, release_id, document_id)
    content = await file.read()
    repo.add_version(
        conn,
        doc["id"],
        file.filename or doc["title"],
        file.content_type or "application/octet-stream",
        content,
        principal.subject or None,
    )
    return repo.get_document_meta(conn, doc["id"])


@router.get("/{release_id}/documents/{document_id}/versions/{version_id}/content")
def download_version(
    release_id: int,
    document_id: int,
    version_id: int,
    conn: psycopg.Connection = Depends(get_conn),
):
    """Stream the bytes of a specific version (any version, current or older)."""
    _require_release(conn, release_id)
    _require_document(conn, release_id, document_id)
    row = repo.get_version_content(conn, version_id)
    if row is None or row["document_id"] != document_id:
        raise HTTPException(404, "Version not found")
    return Response(
        content=bytes(row["content"]),
        media_type=row["content_type"],
        headers={"Content-Disposition": f'attachment; filename="{row["filename"]}"'},
    )


@router.delete(
    "/{release_id}/documents/{document_id}",
    status_code=204,
    dependencies=[Depends(require_role(ROLE_RELEASE_MANAGER, ROLE_ADMIN))],
)
def delete_document(
    release_id: int, document_id: int, conn: psycopg.Connection = Depends(get_conn)
):
    """Delete a document and all of its versions."""
    _require_document(conn, release_id, document_id)
    repo.delete_document(conn, document_id)
