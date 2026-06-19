"""/api/v1/release — release lifecycle: CRUD, checks, artifacts, docs,
state transitions, inheritance, and install pipeline triggering."""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.core.config import settings
from app.core.jwt_verify import (
    ROLE_ADMIN,
    ROLE_DEVELOPER,
    ROLE_RELEASE_MANAGER,
    Principal,
    current_principal,
    require_role,
)
from app.db.pool import get_conn
from app.integrations import llm, trackers
from app.integrations.pipeline import get_runner
from app.repositories import config as config_repo
from app.repositories import jira_issues as jira_repo
from app.repositories import products as products_repo
from app.repositories import releases as repo
from app.services import appconfig
from app.schemas.models import (
    ArtifactMeta,
    AuditEntry,
    Check,
    CheckCreate,
    CheckUpdate,
    DocumentationMeta,
    InheritRequest,
    JiraIssue,
    JiraSyncRequest,
    Release,
    ReleaseCreate,
    ReleaseStatusSummary,
    RequiredDoc,
    TransitionRequest,
)
from app.services import audit
from app.services.state_machine import StateError, StateMachine

router = APIRouter()

# State name that triggers the production sync/install pipeline (docs: Approved).
PIPELINE_TRIGGER_STATE = "Approved"


def get_state_machine(request: Request) -> StateMachine:
    return request.app.state.state_machine


def _split(csv: str) -> list[str]:
    return [s.strip() for s in csv.split(",") if s.strip()]


def _parse_required_docs(csv: str) -> list[tuple[str, str]]:
    """Parse ``Label=keyword,...`` into (label, keyword) pairs."""
    pairs: list[tuple[str, str]] = []
    for item in _split(csv):
        label, _, keyword = item.partition("=")
        label = label.strip()
        keyword = (keyword or label).strip().lower()
        if label:
            pairs.append((label, keyword))
    return pairs


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
    # Seed the release with the organisation's default checklist.
    for tpl in config_repo.list_check_templates(conn):
        repo.add_check(conn, row["id"], tpl["label"], tpl["phase"])
    audit.record(conn, entity_type="release", entity_id=row["id"],
                 action="created", operator=principal.subject, new_value=row["state"])
    return row


@router.get("/{release_id}", response_model=Release)
def get_release(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    return _load(conn, release_id)


# --- Status summary & history ----------------------------------------------
@router.get("/{release_id}/status", response_model=ReleaseStatusSummary)
def release_status(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    """Readiness overview for a release: open (not-closed) Jira issues, the
    required-documentation checklist, and outstanding checks."""
    rel = _load(conn, release_id)

    # Any synced issue whose status is not a closed one (default: only "Done")
    # counts as open — regardless of issue type.
    closed = {s.lower() for s in _split(settings.closed_bug_statuses)}
    issues = jira_repo.list_by_release(conn, release_id)
    open_bugs = [i for i in issues if i["status"].lower() not in closed]

    published = [d["name"].lower() for d in repo.list_documentation(conn, release_id)
                 if not d["is_draft"]]
    required = [
        RequiredDoc(label=label, present=any(keyword in name for name in published))
        for label, keyword in _parse_required_docs(settings.required_docs)
    ]
    missing = [d.label for d in required if not d.present]

    checks = repo.list_checks(conn, release_id)
    pending = sum(1 for c in checks if not c["done"])

    return ReleaseStatusSummary(
        release_id=release_id,
        state=rel["state"],
        open_bug_count=len(open_bugs),
        open_bugs=open_bugs,
        required_docs=required,
        missing_docs=missing,
        pending_checks=pending,
        total_checks=len(checks),
        is_ready=not open_bugs and not missing and pending == 0,
    )


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
    rel = _load(conn, release_id)

    trans = sm.transition(rel["state"], body.transition)
    if trans is None:
        # Not a legal transition out of the current state — reuse the state
        # machine's descriptive error message.
        try:
            sm.apply(rel["state"], body.transition)
        except StateError as exc:
            raise HTTPException(409, str(exc)) from exc

    allowed_roles = appconfig.transition_roles(conn, sm, rel["state"], body.transition)
    if not principal.has_any(allowed_roles):
        raise HTTPException(
            403,
            f"Transition '{body.transition}' requires one of roles: "
            f"{', '.join(sorted(allowed_roles))}",
        )

    new_state = trans.target
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


@router.delete("/checks/{check_id}", status_code=204,
               dependencies=[Depends(require_role(ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def delete_check(check_id: int, conn: psycopg.Connection = Depends(get_conn)):
    if not repo.delete_check(conn, check_id):
        raise HTTPException(404, "Check not found")


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
    """Draft release notes from the tracked issues via the configured LLM
    engine (Claude or Ollama; falls back to a deterministic stub)."""
    rel = _load(conn, release_id)
    cfg = appconfig.effective(conn)
    query, filter_kind = _build_query(cfg, rel, None)
    repo_slug = _product_repo(conn, rel)
    issues = trackers.fetch_issues(cfg, query, repo=repo_slug, filter_kind=filter_kind)
    try:
        draft = llm.get_release_note_service(cfg.llm).draft_release_notes(rel["version"], issues)
    except Exception as exc:  # surface engine/credential errors clearly
        raise HTTPException(502, f"LLM generation failed: {exc}") from exc
    return repo.add_documentation(
        conn, release_id, "release-notes-draft.md", "text/markdown",
        draft.encode("utf-8"), is_draft=True,
    )


# --- Issue-tracker integration (Jira / GitHub, stub by default) ------------
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


@router.post("/{release_id}/jira/sync", response_model=list[JiraIssue],
             dependencies=[Depends(require_role(ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def sync_jira(
    release_id: int,
    body: JiraSyncRequest,
    conn: psycopg.Connection = Depends(get_conn),
    principal: Principal = Depends(current_principal),
):
    """Fetch the issues contained in this release from the active tracker
    (Jira or GitHub, per configuration) and cache them.

    Trackers are stubbed unless enabled, so this is safe to run locally
    end-to-end. The stub is refresh-aware: the first sync returns a mix of
    open/closed issues, and re-syncing reports them all as Done.
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
    previous = jira_repo.list_by_release(conn, release_id)
    try:
        issues = trackers.fetch_issues(
            cfg, query, repo=repo_slug, filter_kind=filter_kind, previous=previous
        )
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


# --- Install pipeline (manual trigger) -------------------------------------
@router.post("/{release_id}/install",
             dependencies=[Depends(require_role(ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def install_release(release_id: int, conn: psycopg.Connection = Depends(get_conn)):
    rel = _load(conn, release_id)
    return get_runner("gitlab-ci").trigger(
        release_id, ref=rel["version"], variables={"version": rel["version"]}
    )
