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
from app.repositories import releases as repo
from app.services import appconfig
from app.schemas.models import (
    ArtifactMeta,
    AuditEntry,
    InheritRequest,
    Issue,
    IssueDetail,
    IssueFilter,
    IssueFilterView,
    IssueMembershipResult,
    IssueRef,
    IssueSearch,
    IssueSearchResult,
    Release,
    ReleaseBugCount,
    ReleaseCreate,
    ReleaseStatusSummary,
    TransitionRequest,
)
from app.services import audit
from app.services import issues as issues_svc
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


def _tracker_call(fn, *args, **kwargs):
    """Run a tracker query, mapping its failures onto HTTP.

    Every issue read goes to the ticketing system, so every one of them can fail
    — and none of them may fail *quietly*. An empty issue list is a meaningful
    answer ("this release has no open work"), so a tracker that could not be
    asked must surface as an error rather than as no issues.
    """
    try:
        return fn(*args, **kwargs)
    except trackers.IssueNotFound as exc:
        raise HTTPException(404, f"Issue {exc} does not exist in the active tracker") from exc
    except trackers.MembershipNotEnforceable as exc:
        # Not a failure of the tracker — a criteria no edit to a ticket can satisfy.
        # 422 so the operator is told to fix the criteria, not to retry.
        raise HTTPException(422, str(exc)) from exc
    except issues_svc.IssueCriteriaError as exc:
        raise HTTPException(422, str(exc)) from exc
    except trackers.TrackerNotConfigured as exc:
        raise HTTPException(503, f"The issue tracker cannot be queried: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (trackers.TrackerError, httpx.HTTPError) as exc:
        raise HTTPException(502, f"Tracker query failed: {exc}") from exc


# --- Release CRUD ----------------------------------------------------------
@router.post("", response_model=Release, status_code=201)
def create_release(
    body: ReleaseCreate,
    conn: psycopg.Connection = Depends(get_conn),
    sm: StateMachine = Depends(get_state_machine),
    principal: Principal = Depends(current_principal),
):
    """Create a release from a version and the search criteria that says which
    tickets it contains (e.g. label = v0.0.1).

    The criteria is stored with the release and is what every later question
    about its issues is put to the ticketing system as. Preview the tickets a
    criteria selects with ``POST /issues/search`` before creating the release.
    """
    try:
        return release_ops.create_release(
            conn, sm, principal,
            product_id=body.product_id,
            version=body.version,
            short_description=body.short_description,
            filter_mode=body.issue_filter.mode,
            filter_value=body.issue_filter.value,
        )
    except release_ops.ReleaseActionError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("/{release_id}", response_model=Release)
def get_release(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    return _load(conn, release_id)


@router.delete("/{release_id}", status_code=204)
def delete_release(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """Permanently delete a release and all its assets (artifacts, documents,
    issue criteria). Cannot be undone."""
    if not repo.delete(conn, release_id):
        raise HTTPException(404, "Release not found")


# --- Status summary & history ----------------------------------------------
@router.get("/{release_id}/status", response_model=ReleaseStatusSummary)
def release_status(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """Readiness overview for a release: its open (not-closed) tickets, read from
    the ticketing system now, and the uploaded document types.

    Fails with 502/503 when the tracker cannot be reached. That is deliberate: the
    alternative — reporting a release as ready because we could not find out
    otherwise — is the failure this endpoint exists to prevent.
    """
    return _tracker_call(compute_status, conn, _load(conn, release_id))


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
    """Create a new release inheriting all assets of a (typically rejected) one —
    including the search criteria that defines which tickets it contains, since it
    carries the same work forward."""
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
    issues_svc.copy_criteria(conn, source_id=parent["id"], target_id=child["id"])
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


# --- Issues (always read live from the ticketing system) --------------------
# There is no sync and no stored issue list. A release stores the *criteria* that
# says which tickets belong to it; these endpoints resolve that criteria against
# the active tracker on every call and return what it says right now.
@router.post("/issues/search", response_model=IssueSearchResult)
def search_issues(body: IssueSearch, conn: psycopg.Connection = Depends(get_conn)):
    """Run a search criteria against the tracker for a product, with no release
    involved — the preview shown while creating a release.

    The operator picks a criteria (e.g. label = v0.0.1), sees the tickets it
    actually finds, and only then creates the release with it. A criteria that
    selects the wrong work is much cheaper to notice here than afterwards.
    """
    cfg = appconfig.effective(conn)
    query, issues = _tracker_call(
        issues_svc.search, conn, cfg, body.product_id, body.mode, body.value
    )
    return IssueSearchResult(
        query=query,
        total=len(issues),
        bug_count=trackers.count_bugs(issues),
        issues=[Issue(**i) for i in issues],
    )


@router.get("/{release_id}/issues", response_model=list[Issue])
def list_issues(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """The tickets this release contains, as the tracker reports them now."""
    rel = _load(conn, release_id)
    cfg = appconfig.effective(conn)
    issues = _tracker_call(issues_svc.for_release, conn, cfg, rel)
    return [Issue(**i) for i in issues]


@router.get("/{release_id}/issue", response_model=IssueDetail)
def get_issue(
    release_id: int,
    key: str = Query(description="Issue key, e.g. 'REL-1' or '#12'"),
    conn: psycopg.Connection = Depends(get_conn),
):
    """One issue's full detail: key, summary, description, status, and the link to
    it in the ticketing system (plus people and timestamps when the tracker has
    them).

    The key is passed as a query parameter because GitHub's ('#12') would
    otherwise have to survive the URL path.
    """
    rel = _load(conn, release_id)
    cfg = appconfig.effective(conn)
    return _tracker_call(issues_svc.detail, conn, cfg, rel, key)


# --- Which tickets the release contains ------------------------------------
# Membership lives in the ticketing system, not here: a ticket is in a release
# because it matches the release's criteria. So adding one *edits the ticket* until
# it does — criteria `label = v0.0.1` -> the label v0.0.1 is added to the ticket —
# and removing one edits it back. The change is made where everyone can see it.
@router.post("/{release_id}/issues/add", response_model=IssueMembershipResult)
def add_issue(
    release_id: int,
    body: IssueRef,
    conn: psycopg.Connection = Depends(get_conn),
    principal: Principal = Depends(current_principal),
):
    return _set_membership(conn, principal, release_id, body.key, member=True)


@router.post("/{release_id}/issues/remove", response_model=IssueMembershipResult)
def remove_issue(
    release_id: int,
    body: IssueRef,
    conn: psycopg.Connection = Depends(get_conn),
    principal: Principal = Depends(current_principal),
):
    return _set_membership(conn, principal, release_id, body.key, member=False)


def _set_membership(
    conn: psycopg.Connection,
    principal: Principal,
    release_id: int,
    key: str,
    *,
    member: bool,
) -> IssueMembershipResult:
    rel = _load(conn, release_id)
    cfg = appconfig.effective(conn)
    result = _tracker_call(issues_svc.set_membership, conn, cfg, rel, key, member=member)
    audit.record(
        conn, entity_type="release", entity_id=release_id,
        action="issue_added" if member else "issue_removed",
        operator=principal.subject,
        new_value=f'{result["key"]} ({result["criteria"]})',
    )
    return IssueMembershipResult(
        key=result["key"],
        member=result["member"],
        criteria=result["criteria"],
        total=result["total"],
        issues=[Issue(**i) for i in result["issues"]],
    )


@router.get("/{release_id}/bugs/count", response_model=ReleaseBugCount)
def release_bug_count(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """Total bugs in this release, counted over the same issue set the readiness
    gate uses — the release's stored criteria."""
    rel = _load(conn, release_id)
    cfg = appconfig.effective(conn)
    issues = _tracker_call(issues_svc.for_release, conn, cfg, rel)
    return ReleaseBugCount(
        release_id=release_id,
        filter=issues_svc.release_query(conn, cfg, rel),
        total_bugs=trackers.count_bugs(issues),
    )


# --- The release's issue criteria ------------------------------------------
@router.get("/{release_id}/issue-filter", response_model=IssueFilterView | None)
def get_issue_filter(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """The search criteria stored for this release. ``null`` only for releases
    created before criteria were recorded — those fall back to the tracker's
    native release grouping (a milestone or fixVersion named after the version).
    """
    _load(conn, release_id)
    row = issues_svc.get_criteria(conn, release_id)
    if row is None:
        return None
    return IssueFilterView(
        release_id=row["release_id"],
        mode=row["filter_mode"],
        value=row["filter_value"],
        updated_at=row["updated_at"],
    )


@router.put("/{release_id}/issue-filter", response_model=IssueFilterView)
def save_issue_filter(
    release_id: int,
    body: IssueFilter,
    conn: psycopg.Connection = Depends(get_conn),
    principal: Principal = Depends(current_principal),
):
    """Change which tickets this release contains.

    Audited: the criteria decides what the readiness gate is deciding *over*, so
    a change to it is as consequential as a state change and belongs in the
    release's history.
    """
    _load(conn, release_id)
    cfg = appconfig.effective(conn)
    mode, value = _tracker_call(issues_svc.validate_criteria, cfg, body.mode, body.value)

    previous = issues_svc.get_criteria(conn, release_id)
    row = issues_svc.save_criteria(conn, release_id, mode, value)
    audit.record(
        conn, entity_type="release", entity_id=release_id, action="issue_criteria",
        operator=principal.subject,
        old_value=(f'{previous["filter_mode"]} = {previous["filter_value"]}'
                   if previous else None),
        new_value=f"{mode} = {value}",
    )
    return IssueFilterView(
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
