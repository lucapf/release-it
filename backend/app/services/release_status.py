"""Release readiness aggregation — the single source of truth shared by the
release API, the status endpoint, the transition guards, and the LLM assistant.

Keeping this in a service (rather than in the ``/api/v1/release`` router) lets the
chat assistant compute the same view the REST endpoints do, without importing the
FastAPI layer.
"""
from __future__ import annotations

import psycopg

from app.core.config import settings
from app.repositories import documents as documents_repo
from app.repositories import jira_issues as jira_repo
from app.schemas.models import ReleaseStatusSummary
from app.services.state_machine import document_guard_type, is_document_guard


def _split(csv: str) -> list[str]:
    return [s.strip() for s in csv.split(",") if s.strip()]


def compute_status(conn: psycopg.Connection, rel: dict) -> ReleaseStatusSummary:
    """Aggregate a release's readiness: open (not-closed) tracker issues and the
    uploaded document types. Single source of truth for the status endpoint,
    the transition guards, and the assistant."""
    release_id = rel["id"]
    # Any synced issue whose status is not a closed one (default: only "Done")
    # counts as open — regardless of issue type.
    closed = {s.lower() for s in _split(settings.closed_bug_statuses)}
    issues = jira_repo.list_by_release(conn, release_id)
    open_bugs = [i for i in issues if i["status"].lower() not in closed]

    present_doc_types = documents_repo.present_types(conn, release_id)

    return ReleaseStatusSummary(
        release_id=release_id,
        state=rel["state"],
        open_bug_count=len(open_bugs),
        open_bugs=open_bugs,
        present_doc_types=sorted(present_doc_types),
        is_ready=not open_bugs,
    )


def unmet_requirements(
    requires: frozenset[str], status: ReleaseStatusSummary
) -> list[str]:
    """Human-readable reasons a guarded transition is blocked (empty = allowed).
    Guard names mirror those declared in states.yaml ``requires``."""
    reasons: list[str] = []
    if "no_open_issues" in requires and status.open_bug_count > 0:
        reasons.append(f"{status.open_bug_count} open issue(s) must be closed first")
    present = set(status.present_doc_types)
    for guard in requires:
        if is_document_guard(guard):
            doc_type = document_guard_type(guard)
            if doc_type not in present:
                reasons.append(f'missing required document: "{doc_type}"')
    return reasons
