"""/api/v1/release — release lifecycle: CRUD, checks, artifacts, docs,
state transitions, inheritance, and install pipeline triggering."""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.core.jwt_verify import (
    ROLE_ADMIN,
    ROLE_DEVELOPER,
    ROLE_QA_MANAGER,
    ROLE_RELEASE_MANAGER,
    Principal,
    current_principal,
    require_role,
)
from app.db.pool import get_conn
from app.integrations import jira
from app.integrations.llm import get_release_note_service
from app.integrations.pipeline import get_runner
from app.repositories import jira_issues as jira_repo
from app.repositories import products as products_repo
from app.repositories import releases as repo
from app.schemas.models import (
    ArtifactMeta,
    Check,
    CheckCreate,
    CheckUpdate,
    DocumentationMeta,
    InheritRequest,
    JiraIssue,
    JiraSyncRequest,
    Release,
    ReleaseCreate,
    TransitionRequest,
)
from app.services import audit
from app.services.state_machine import StateError, StateMachine

router = APIRouter()

# State name that triggers the production sync/install pipeline (docs: Approved).
PIPELINE_TRIGGER_STATE = "Approved"


def get_state_machine(request: Request) -> StateMachine:
    return request.app.state.state_machine


def _load(conn: psycopg.Connection, release_id: int) -> dict:
    row = repo.get(conn, release_id)
    if row is None:
        raise HTTPException(404, "Release not found")
    return row


# --- Release CRUD ----------------------------------------------------------
@router.post("", response_model=Release, status_code=201,
             dependencies=[Depends(require_role(ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def create_release(
    body: ReleaseCreate,
    conn: psycopg.Connection = Depends(get_conn),
    sm: StateMachine = Depends(get_state_machine),
    principal: Principal = Depends(current_principal),
):
    if products_repo.get(conn, body.product_id) is None:
        raise HTTPException(404, "Product not found")
    row = repo.create(
        conn,
        product_id=body.product_id,
        version=body.version,
        state=sm.initial_state,
        short_description=body.short_description,
    )
    audit.record(conn, entity_type="release", entity_id=row["id"],
                 action="created", operator=principal.subject, new_value=row["state"])
    return row


@router.get("/{release_id}", response_model=Release)
def get_release(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    return _load(conn, release_id)


# --- State transitions -----------------------------------------------------
@router.post("/{release_id}/transition", response_model=Release,
             dependencies=[Depends(require_role(ROLE_QA_MANAGER, ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def transition_release(
    release_id: int,
    body: TransitionRequest,
    conn: psycopg.Connection = Depends(get_conn),
    sm: StateMachine = Depends(get_state_machine),
    principal: Principal = Depends(current_principal),
):
    rel = _load(conn, release_id)
    try:
        new_state = sm.apply(rel["state"], body.transition)
    except StateError as exc:
        raise HTTPException(409, str(exc)) from exc

    updated = repo.set_state(conn, release_id, new_state)
    audit.record(conn, entity_type="release", entity_id=release_id,
                 action="status_update", operator=principal.subject,
                 old_value=rel["state"], new_value=new_state)

    # Version-2 feature: on Approved, run the production sync/install pipeline.
    if new_state == PIPELINE_TRIGGER_STATE:
        get_runner("gitlab-ci").trigger(
            release_id, ref=updated["version"], variables={"version": updated["version"]}
        )
    return updated


# --- Release inheritance ---------------------------------------------------
@router.post("/{release_id}/inherit", response_model=Release, status_code=201,
             dependencies=[Depends(require_role(ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def inherit_release(
    release_id: int,
    body: InheritRequest,
    conn: psycopg.Connection = Depends(get_conn),
    sm: StateMachine = Depends(get_state_machine),
    principal: Principal = Depends(current_principal),
):
    """Create a new release inheriting all assets of a (typically rejected) one."""
    parent = _load(conn, release_id)
    child = repo.create(
        conn,
        product_id=parent["product_id"],
        version=body.version,
        state=sm.initial_state,
        short_description=parent["short_description"],
        parent_release_id=parent["id"],
    )
    repo.clone_assets(conn, source_id=parent["id"], target_id=child["id"])
    audit.record(conn, entity_type="release", entity_id=child["id"],
                 action="inherited", operator=principal.subject,
                 old_value=str(parent["id"]), new_value=str(child["id"]))
    return child


# --- Checks ----------------------------------------------------------------
@router.get("/{release_id}/checks", response_model=list[Check])
def list_checks(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    _load(conn, release_id)
    return repo.list_checks(conn, release_id)


@router.post("/{release_id}/checks", response_model=Check, status_code=201,
             dependencies=[Depends(require_role(ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def add_check(release_id: int, body: CheckCreate, conn: psycopg.Connection = Depends(get_conn)):
    _load(conn, release_id)
    return repo.add_check(conn, release_id, body.label, body.phase)


@router.patch("/checks/{check_id}", response_model=Check,
              dependencies=[Depends(require_role(ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def update_check(check_id: int, body: CheckUpdate, conn: psycopg.Connection = Depends(get_conn)):
    row = repo.set_check_done(conn, check_id, body.done)
    if row is None:
        raise HTTPException(404, "Check not found")
    return row


# --- Artifacts (bytea) -----------------------------------------------------
@router.post("/{release_id}/artifacts", response_model=ArtifactMeta, status_code=201,
             dependencies=[Depends(require_role(ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
async def upload_artifact(
    release_id: int, file: UploadFile, conn: psycopg.Connection = Depends(get_conn)
):
    _load(conn, release_id)
    content = await file.read()
    return repo.add_artifact(
        conn, release_id, file.filename or "artifact",
        file.content_type or "application/octet-stream", content,
    )


@router.get("/{release_id}/artifacts", response_model=list[ArtifactMeta])
def list_artifacts(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    _load(conn, release_id)
    return repo.list_artifacts(conn, release_id)


@router.get("/artifacts/{artifact_id}/content")
def download_artifact(artifact_id: int, conn: psycopg.Connection = Depends(get_conn)):
    row = repo.get_artifact_content(conn, artifact_id)
    if row is None:
        raise HTTPException(404, "Artifact not found")
    return Response(
        content=bytes(row["content"]),
        media_type=row["content_type"],
        headers={"Content-Disposition": f'attachment; filename="{row["name"]}"'},
    )


# --- Documentation / release notes -----------------------------------------
@router.get("/{release_id}/documentation", response_model=list[DocumentationMeta])
def list_documentation(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    _load(conn, release_id)
    return repo.list_documentation(conn, release_id)


@router.post("/{release_id}/documentation", response_model=DocumentationMeta, status_code=201,
             dependencies=[Depends(require_role(ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
async def upload_documentation(
    release_id: int, file: UploadFile, conn: psycopg.Connection = Depends(get_conn)
):
    _load(conn, release_id)
    content = await file.read()
    return repo.add_documentation(
        conn, release_id, file.filename or "release-notes.md",
        file.content_type or "text/markdown", content, is_draft=False,
    )


@router.post("/{release_id}/release-notes/generate", response_model=DocumentationMeta, status_code=201,
             dependencies=[Depends(require_role(ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def generate_release_notes(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """Draft release notes from Jira issues via the (stub) LLM service."""
    rel = _load(conn, release_id)
    issues = jira.fetch_issues(f'fixVersion = "{rel["version"]}"')
    draft = get_release_note_service().draft_release_notes(rel["version"], issues)
    return repo.add_documentation(
        conn, release_id, "release-notes-draft.md", "text/markdown",
        draft.encode("utf-8"), is_draft=True,
    )


# --- Jira integration (stub) -----------------------------------------------
def _build_jql(release: dict, body: JiraSyncRequest) -> str:
    """Resolve the effective JQL: explicit query > release label > version."""
    if body.jql and body.jql.strip():
        return body.jql.strip()
    if body.release_label and body.release_label.strip():
        return f'labels = "{body.release_label.strip()}"'
    return f'fixVersion = "{release["version"]}"'


@router.post("/{release_id}/jira/sync", response_model=list[JiraIssue],
             dependencies=[Depends(require_role(ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def sync_jira(
    release_id: int,
    body: JiraSyncRequest,
    conn: psycopg.Connection = Depends(get_conn),
    principal: Principal = Depends(current_principal),
):
    """Fetch the issues contained in this release from Jira and cache them.

    Filter by a release label or a custom JQL query (see ``JiraSyncRequest``).
    Jira is stubbed unless ``JIRA_ENABLED`` is set, so this is safe to run
    locally end-to-end.
    """
    rel = _load(conn, release_id)
    jql = _build_jql(rel, body)
    issues = jira.fetch_issues(jql)
    saved = jira_repo.replace_for_release(conn, release_id, issues)
    audit.record(conn, entity_type="release", entity_id=release_id,
                 action="jira_sync", operator=principal.subject, new_value=jql)
    return saved


@router.get("/{release_id}/jira/issues", response_model=list[JiraIssue])
def list_jira_issues(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    _load(conn, release_id)
    return jira_repo.list_by_release(conn, release_id)


# --- Install pipeline (manual trigger) -------------------------------------
@router.post("/{release_id}/install",
             dependencies=[Depends(require_role(ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def install_release(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    rel = _load(conn, release_id)
    return get_runner("gitlab-ci").trigger(
        release_id, ref=rel["version"], variables={"version": rel["version"]}
    )
