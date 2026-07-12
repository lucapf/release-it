"""Readiness guards: what blocks a guarded transition.

`document:<Type>` requires the document to be attached *and* approved — a draft
document leaves the transition blocked.
"""
from __future__ import annotations

from app.schemas.models import ReleaseStatusSummary
from app.services.release_status import unmet_requirements


def _status(present=(), approved=(), open_bugs=0) -> ReleaseStatusSummary:
    return ReleaseStatusSummary(
        release_id=1,
        state="Draft",
        open_bug_count=open_bugs,
        open_bugs=[],
        present_doc_types=list(present),
        approved_doc_types=list(approved),
        is_ready=not open_bugs,
    )


def test_no_guards_never_blocks():
    assert unmet_requirements(frozenset(), _status()) == []


def test_open_issues_block_no_open_issues_guard():
    reasons = unmet_requirements(frozenset({"no_open_issues"}), _status(open_bugs=3))
    assert reasons == ["3 open issue(s) must be closed first"]


def test_approved_document_satisfies_document_guard():
    status = _status(present=["Release Note"], approved=["Release Note"])
    assert unmet_requirements(frozenset({"document:Release Note"}), status) == []


def test_draft_document_does_not_satisfy_document_guard():
    """The document is attached but still DRAFT — the guard must stay unmet."""
    status = _status(present=["Release Note"], approved=[])
    reasons = unmet_requirements(frozenset({"document:Release Note"}), status)
    assert reasons == ['required document "Release Note" must be approved']


def test_missing_document_is_reported_as_missing_not_unapproved():
    status = _status(present=[], approved=[])
    reasons = unmet_requirements(frozenset({"document:Release Note"}), status)
    assert reasons == ['missing required document: "Release Note"']


def test_guards_are_independent_per_document_type():
    status = _status(
        present=["Release Note", "Install Notes"], approved=["Release Note"]
    )
    reasons = unmet_requirements(
        frozenset({"document:Release Note", "document:Install Notes"}), status
    )
    assert reasons == ['required document "Install Notes" must be approved']
