"""Release lifecycle *actions* — create and transition — as reusable services.

Both the ``/api/v1/release`` REST routes and the LLM assistant perform these
actions; keeping the role checks, readiness guards, audit
logging and pipeline triggering here guarantees the assistant can never bypass
the enforcement the UI goes through. Callers translate :class:`ReleaseActionError`
into their own error surface (HTTP status / tool error message).
"""
from __future__ import annotations

import httpx
import psycopg
from psycopg import errors as pg_errors

from app.core.config import settings
from app.core.identity import Principal
from app.integrations import trackers
from app.integrations.pipeline import get_runner
from app.repositories import products as products_repo
from app.repositories import releases as repo
from app.services import appconfig, audit
from app.services import issues as issues_svc
from app.services.release_status import guard_status, unmet_requirements
from app.services.state_machine import StateError, StateMachine

# State name that triggers the production sync/install pipeline (docs: Approved).
PIPELINE_TRIGGER_STATE = "Approved"


class ReleaseActionError(Exception):
    """A create/transition action was rejected. ``status_code`` mirrors the HTTP
    status the REST layer would return (404/403/409) so routes can re-raise it."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def create_release(
    conn: psycopg.Connection,
    sm: StateMachine,
    principal: Principal,
    *,
    product_id: int,
    version: str,
    short_description: str = "",
    filter_mode: str,
    filter_value: str,
) -> dict:
    """Create a release in the initial workflow state, store the search criteria
    that defines which tickets it contains, and audit both.

    The criteria is not optional: it is how every later question about this
    release's issues ("is anything still open?", "how many bugs?") is put to the
    ticketing system. A release without one would have no defensible answer —
    only a provider default that happens to guess at the version.
    """
    if products_repo.get(conn, product_id) is None:
        raise ReleaseActionError(404, "Product not found")
    cfg = appconfig.effective(conn)
    try:
        mode, value = issues_svc.validate_criteria(cfg, filter_mode, filter_value)
    except issues_svc.IssueCriteriaError as exc:
        raise ReleaseActionError(422, str(exc)) from exc

    try:
        row = repo.create(
            conn,
            product_id=product_id,
            version=version,
            state=sm.initial_state,
            short_description=short_description,
        )
    except pg_errors.UniqueViolation as exc:
        raise ReleaseActionError(
            409, f"A release with version '{version}' already exists for this product"
        ) from exc

    issues_svc.save_criteria(conn, row["id"], mode, value)
    audit.record(conn, entity_type="release", entity_id=row["id"],
                 action="created", operator=principal.subject, new_value=row["state"])
    audit.record(conn, entity_type="release", entity_id=row["id"],
                 action="issue_criteria", operator=principal.subject,
                 new_value=f"{mode} = {value}")
    return row


def _tracker_failure(exc: Exception) -> ReleaseActionError:
    """A tracker that could not be asked refuses the transition (503).

    Fail closed. For a release gate, "we could not check" must never quietly
    become "the check passed" — the alternative, answering the guard from an
    empty issue list, reads as "nothing is open" and approves the release.
    """
    if isinstance(exc, trackers.TrackerNotConfigured):
        return ReleaseActionError(503, f"Cannot verify this release's issues: {exc}")
    return ReleaseActionError(
        503, f"Cannot verify this release's issues — the tracker is unreachable: {exc}"
    )


def apply_transition(
    conn: psycopg.Connection,
    sm: StateMachine,
    principal: Principal,
    release_id: int,
    transition: str,
    note: str = "",
) -> dict:
    """Apply a workflow transition, enforcing (in order) legality, per-transition
    roles, and the readiness guards. On reaching ``Approved`` with GitLab CI
    configured, the install pipeline is triggered.

    A guard backed by the tracker (``no_open_issues``) is decided on the tracker's
    live answer — the release's issues are read from the ticketing system as the
    guard is evaluated — and the transition is refused outright if the tracker
    cannot be reached. A transition that declares no such guard (Reject, Cancel)
    never touches the tracker, so it still works when the tracker is down.

    ``note`` is an optional free-text comment the operator may attach to explain
    the state change; it is stored on the audit entry."""
    rel = repo.get(conn, release_id)
    if rel is None:
        raise ReleaseActionError(404, "Release not found")

    trans = sm.transition(rel["state"], transition)
    if trans is None:
        # Not a legal transition out of the current state — reuse the state
        # machine's descriptive error message.
        try:
            sm.apply(rel["state"], transition)
        except StateError as exc:
            raise ReleaseActionError(409, str(exc)) from exc

    allowed_roles = appconfig.transition_roles(conn, sm, rel["state"], transition)
    if not principal.has_any(allowed_roles):
        raise ReleaseActionError(
            403,
            f"Transition '{transition}' requires one of roles: "
            f"{', '.join(sorted(allowed_roles))}",
        )

    # Readiness guards declared in states.yaml (e.g. Approve needs all issues
    # closed and the required docs present). Reject and Cancel stay unguarded.
    try:
        status = guard_status(conn, rel, trans.requires)
    except (trackers.TrackerError, httpx.HTTPError, ValueError) as exc:
        raise _tracker_failure(exc) from exc
    unmet = unmet_requirements(trans.requires, status)
    if unmet:
        raise ReleaseActionError(
            409,
            f"Cannot '{transition}' release v{rel['version']}: " + "; ".join(unmet),
        )

    new_state = trans.target
    updated = repo.set_state(conn, release_id, new_state)
    audit.record(conn, entity_type="release", entity_id=release_id,
                 action="status_update", operator=principal.subject,
                 old_value=rel["state"], new_value=new_state,
                 note=(note or "").strip() or None)

    # On Approved, run the production sync/install pipeline — only when GitLab CI
    # is actually configured (there is no stub to fall back on).
    if new_state == PIPELINE_TRIGGER_STATE and settings.gitlab_enabled:
        get_runner("gitlab-ci").trigger(
            release_id, ref=updated["version"], variables={"version": updated["version"]}
        )
    return updated
