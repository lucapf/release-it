"""/api/v1/release — release lifecycle: CRUD, artifacts, docs,
state transitions, inheritance, and install pipeline triggering."""
from __future__ import annotations

import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app.core.identity import Principal, current_principal
from app.db.pool import get_conn
from app.integrations import trackers
from app.integrations.pipeline import get_runner
from app.repositories import jira_issues as jira_repo
from app.repositories import products as products_repo
from app.repositories import releases as repo
from app.repositories import sync_filters as filters_repo
from app.services import appconfig
from app.schemas.models import (
    ArtifactMeta,
    AuditEntry,
    InheritRequest,
    IssueDetail,
    JiraIssue,
    JiraSyncRequest,
    Release,
    ReleaseBugCount,
    SyncFilter,
    SyncFilterView,
    ReleaseCreate,
    ReleaseStatusSummary,
    TransitionRequest,
)
from app.services import audit
from app.services import release_ops
from app.services.release_status import compute_status
from app.services.state_machine import StateMachine

router = APIRouter()


def get_state_machine(request: Request) -> StateMachine:
    return request.app.state.state_machine


def _load(conn: psycopg.Connection, release_id: int) -> dict:
    row = repo.get(conn, release_id)
    if row is None:
        raise HTTPException(404, "Release not found")
    return row


# --- Release CRUD ----------------------------------------------------------
@router.post("", response_model=Release, status_code=201)
def create_release(
    body: ReleaseCreate,
    conn: psycopg.Connection = Depends(get_conn),
    sm: StateMachine = Depends(get_state_machine),
    principal: Principal = Depends(current_principal),
):
    try:
        return release_ops.create_release(
            conn, sm, principal,
            product_id=body.product_id,
            version=body.version,
            short_description=body.short_description,
        )
    except release_ops.ReleaseActionError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("/{release_id}", response_model=Release)
def get_release(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    return _load(conn, release_id)


@router.delete("/{release_id}", status_code=204)
def delete_release(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """Permanently delete a release and all its assets (checks, artifacts,
    documents, synced issues). Cannot be undone."""
    if not repo.delete(conn, release_id):
        raise HTTPException(404, "Release not found")


# --- Status summary & history ----------------------------------------------
@router.get("/{release_id}/status", response_model=ReleaseStatusSummary)
def release_status(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """Readiness overview for a release: open (not-closed) tracker issues and
    the uploaded document types."""
    return compute_status(conn, _load(conn, release_id))


@router.get("/{release_id}/history", response_model=list[AuditEntry])
def release_history(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """The audit trail for a release (state changes, sync, inheritance, ...),
    most recent first — each with its operator and timestamp."""
    _load(conn, release_id)
    return audit.list_for(conn, entity_type="release", entity_id=release_id)


# --- State transitions -----------------------------------------------------
@router.post("/{release_id}/transition", response_model=Release)
def transition_release(
    release_id: int,
    body: TransitionRequest,
    conn: psycopg.Connection = Depends(get_conn),
    sm: StateMachine = Depends(get_state_machine),
    principal: Principal = Depends(current_principal),
):
    """Apply a workflow transition. The state machine decides which transitions
    are legal from the current state; the effective roles (admin override >
    states.yaml > default) decide who may perform it — both enforced here, not
    just in the UI."""
    try:
        return release_ops.apply_transition(
            conn, sm, principal, release_id, body.transition, body.note
        )
    except release_ops.ReleaseActionError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


# --- Release inheritance ---------------------------------------------------
@router.post("/{release_id}/inherit", response_model=Release, status_code=201)
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


# --- Artifacts (bytea) -----------------------------------------------------
@router.post("/{release_id}/artifacts", response_model=ArtifactMeta, status_code=201)
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


# --- Issue-tracker integration (Jira / GitHub) -----------------------------
def _build_query(
    cfg: appconfig.EffectiveConfig, release: dict, body: JiraSyncRequest | None
) -> tuple[str, str]:
    """Resolve the tracker filter to ``(query, filter_kind)``.

    * GitHub — a label (``filter_kind="label"``) when one is given, otherwise a
      milestone (``filter_kind="milestone"``) whose title defaults to the
      release version. This matches how releases group issues on GitHub.
    * Jira — always JQL: explicit query > label (``labels = "<label>"``) >
      ``fixVersion = "<version>"``.
    """
    label = (body.release_label or "").strip() if body else ""
    jql = (body.jql or "").strip() if body else ""
    milestone = (body.milestone or "").strip() if body else ""

    if cfg.provider == "github":
        if label:
            return label, "label"
        return (milestone or release["version"]), "milestone"

    if jql:
        return jql, "jql"
    if label:
        return f'labels = "{label}"', "jql"
    return f'fixVersion = "{release["version"]}"', "jql"


def _product_repo(conn: psycopg.Connection, release: dict) -> str:
    """The GitHub 'owner/repo' bound to this release's product (may be blank)."""
    product = products_repo.get(conn, release["product_id"])
    return (product or {}).get("tracker_repo", "") or ""


@router.post("/{release_id}/jira/sync", response_model=list[JiraIssue])
def sync_jira(
    release_id: int,
    body: JiraSyncRequest,
    conn: psycopg.Connection = Depends(get_conn),
    principal: Principal = Depends(current_principal),
):
    """Fetch the issues contained in this release from the active tracker
    (Jira or GitHub, per configuration) and cache them.

    The tracker calls its real backing service (for tests, the Jira tracker is
    pointed at the external jira-stub); when it is not configured there are no
    issues to sync.
    """
    rel = _load(conn, release_id)
    cfg = appconfig.effective(conn)
    query, filter_kind = _build_query(cfg, rel, body)
    repo_slug = _product_repo(conn, rel)
    if cfg.provider == "github" and cfg.github.enabled and not repo_slug:
        raise HTTPException(
            400,
            "No GitHub repository configured for this product. Set it on the "
            "product's Issues tab (e.g. 'owner/repo').",
        )
    try:
        issues = trackers.fetch_issues(cfg, query, repo=repo_slug, filter_kind=filter_kind)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    saved = jira_repo.replace_for_release(conn, release_id, issues)
    audit.record(conn, entity_type="release", entity_id=release_id,
                 action="jira_sync", operator=principal.subject, new_value=query)
    return saved


@router.get("/{release_id}/jira/issues", response_model=list[JiraIssue])
def list_jira_issues(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    _load(conn, release_id)
    return jira_repo.list_by_release(conn, release_id)


@router.get("/{release_id}/jira/issue", response_model=IssueDetail)
def get_jira_issue(
    release_id: int,
    key: str = Query(description="Issue key as cached, e.g. 'REL-1' or '#12'"),
    conn: psycopg.Connection = Depends(get_conn),
):
    """One issue's full detail, fetched live from the active tracker.

    The cached rows carry only what the issue list needs; the description,
    people and timestamps are read on demand so the operator always sees the
    tracker's current state rather than whatever the last sync captured. The
    key is passed as a query parameter because GitHub's ('#12') would otherwise
    have to survive the URL path.
    """
    rel = _load(conn, release_id)
    cfg = appconfig.effective(conn)
    try:
        issue = trackers.fetch_issue(cfg, key, repo=_product_repo(conn, rel))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Tracker query failed: {exc}") from exc
    if issue is None:
        raise HTTPException(404, f"Issue {key} not found in the active tracker")
    return issue


@router.get("/{release_id}/bugs/count", response_model=ReleaseBugCount)
def release_bug_count(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """Total bugs in this release, counted live from the active tracker. The
    filter is always the release label ``v<major>.<minor>.<patch>`` (e.g.
    ``v0.0.1``) derived from the release version."""
    rel = _load(conn, release_id)
    cfg = appconfig.effective(conn)
    label = trackers.release_label(rel["version"])
    repo_slug = _product_repo(conn, rel)
    if cfg.provider == "github" and cfg.github.enabled and not repo_slug:
        raise HTTPException(
            400,
            "No GitHub repository configured for this product. Set it on the "
            "product's Issues tab (e.g. 'owner/repo').",
        )
    query = label if cfg.provider == "github" else f'labels = "{label}"'
    filter_kind = "label" if cfg.provider == "github" else "jql"
    try:
        issues = trackers.fetch_issues(cfg, query, repo=repo_slug, filter_kind=filter_kind)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Tracker query failed: {exc}") from exc
    return ReleaseBugCount(
        release_id=release_id, label=label, total_bugs=trackers.count_bugs(issues)
    )


# --- Saved sync filter (any authenticated operator) ------------------------
@router.get("/{release_id}/sync-filter", response_model=SyncFilterView | None)
def get_sync_filter(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """The persisted tracker filter for this release, or ``null`` if none."""
    _load(conn, release_id)
    row = filters_repo.get(conn, release_id)
    if row is None:
        return None
    return SyncFilterView(
        release_id=row["release_id"],
        mode=row["filter_mode"],
        value=row["filter_value"],
        updated_at=row["updated_at"],
    )


@router.put("/{release_id}/sync-filter", response_model=SyncFilterView)
def save_sync_filter(
    release_id: int,
    body: SyncFilter,
    conn: psycopg.Connection = Depends(get_conn),
    principal: Principal = Depends(current_principal),
):
    """Persist the tracker filter so it is applied automatically next time."""
    _load(conn, release_id)
    row = filters_repo.upsert(conn, release_id, body.mode, body.value)
    return SyncFilterView(
        release_id=row["release_id"],
        mode=row["filter_mode"],
        value=row["filter_value"],
        updated_at=row["updated_at"],
    )


# --- Install pipeline (manual trigger) -------------------------------------
@router.post("/{release_id}/install")
def install_release(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    rel = _load(conn, release_id)
    try:
        return get_runner("gitlab-ci").trigger(
            release_id, ref=rel["version"], variables={"version": rel["version"]}
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
