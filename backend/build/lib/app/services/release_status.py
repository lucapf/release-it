"""Release readiness aggregation — the single source of truth shared by the
release API, the status endpoint, the transition guards, and the LLM assistant.

Keeping this in a service (rather than in the ``/api/v1/release`` router) lets the
chat assistant compute the same view the REST endpoints do, without importing the
FastAPI layer.
"""
from __future__ import annotations

import psycopg

from app.repositories import documents as documents_repo
from app.schemas.models import Issue, ReleaseStatusSummary
from app.services import appconfig, issues as issues_svc
from app.services.state_machine import document_guard_type, is_document_guard

# Guards whose answer belongs to the ticketing system. A transition that declares
# one costs a tracker round trip; one that declares none (Reject, Cancel) must not
# — it would make those transitions impossible whenever the tracker is down.
TRACKER_BACKED_GUARDS = frozenset({"no_open_issues"})


def _summary(
    conn: psycopg.Connection, rel: dict, issues: list[dict]
) -> ReleaseStatusSummary:
    # Whether an issue is finished is the tracker's call, not ours: each provider
    # sets `closed` from its own semantics (Jira's statusCategory, GitHub/GitLab's
    # issue state). Release-It used to re-derive this by matching status names
    # against a configured list, which meant a Jira project whose done-status was
    # called "Resolved" could never satisfy `no_open_issues`.
    open_bugs = [Issue(**i) for i in issues if not i.get("closed")]
    return ReleaseStatusSummary(
        release_id=rel["id"],
        state=rel["state"],
        open_bug_count=len(open_bugs),
        open_bugs=open_bugs,
        present_doc_types=sorted(documents_repo.present_types(conn, rel["id"])),
        approved_doc_types=sorted(documents_repo.approved_types(conn, rel["id"])),
        is_ready=not open_bugs,
    )


def compute_status(conn: psycopg.Connection, rel: dict) -> ReleaseStatusSummary:
    """Aggregate a release's readiness: its open tracker issues, the uploaded
    document types and the approved subset of them.

    The issues are read from the ticketing system on every call — there is no
    cached copy to read instead, and a status that reports a tracker's answer from
    ten minutes ago is a status that can be wrong. Raises when the tracker cannot
    be asked (see :mod:`app.services.issues`); "we could not check" must reach the
    caller as an error, not as a clean bill of health.
    """
    cfg = appconfig.effective(conn)
    return _summary(conn, rel, issues_svc.for_release(conn, cfg, rel))


def guard_status(
    conn: psycopg.Connection, rel: dict, requires: frozenset[str]
) -> ReleaseStatusSummary:
    """The status a transition's guards are evaluated against.

    Identical to :func:`compute_status` when one of the guards is tracker-backed;
    otherwise the tracker is not consulted at all and the summary carries no
    issues. Pass the result to :func:`unmet_requirements` and nothing else: the
    issue-side fields of an unguarded transition's summary describe what was
    checked, not what is true.
    """
    if requires & TRACKER_BACKED_GUARDS:
        return compute_status(conn, rel)
    return _summary(conn, rel, [])


def unmet_requirements(
    requires: frozenset[str], status: ReleaseStatusSummary
) -> list[str]:
    """Human-readable reasons a guarded transition is blocked (empty = allowed).
    Guard names mirror those declared in states.yaml ``requires``."""
    reasons: list[str] = []
    if "no_open_issues" in requires and status.open_bug_count > 0:
        reasons.append(f"{status.open_bug_count} open issue(s) must be closed first")
    present = set(status.present_doc_types)
    approved = set(status.approved_doc_types)
    for guard in requires:
        if is_document_guard(guard):
            doc_type = document_guard_type(guard)
            if doc_type in approved:
                continue
            if doc_type in present:
                reasons.append(f'required document "{doc_type}" must be approved')
            else:
                reasons.append(f'missing required document: "{doc_type}"')
    return reasons
