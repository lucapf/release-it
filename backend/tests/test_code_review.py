"""The advisory AI code review: prompting, budgeting, assembly, storage.

The LLM and the change-set are faked. What matters: the diff budget includes
whole files smallest-first and *names* what it leaves out; every truncation is
visible to both the model and the reader; a run with no baseline or no changes
refuses with a reason instead of producing an empty-but-official report; and
each run lands as a DRAFT document version plus an audit entry.
"""
from __future__ import annotations

import pytest

from app.integrations.git import GitCommit, GitCompare, GitFileDiff
from app.services import code_review, git_changes
from app.services.code_review import ReviewUnavailable, run_code_review
from app.services.git_changes import CommitTickets, ComponentChange, ReleaseChangeSet


class FakePrincipal:
    subject = "op@example.com"


def _change(name="moda", *, files=None, commits=None, status="changed"):
    compare = GitCompare(
        base_ref="v1.0.0", head_ref="v1.1.0",
        files=files if files is not None else [
            GitFileDiff(path="app.py", status="modified", additions=1,
                        deletions=1, patch="@@ small @@"),
        ],
        web_url="https://github.com/acme/moda/compare/v1.0.0...v1.1.0",
    )
    kts = commits if commits is not None else [
        CommitTickets(sha="a" * 40, short_sha="aaaaaaaa",
                      subject="Fix login (#12)", author="Ada", url="",
                      tickets=["#12"]),
        CommitTickets(sha="b" * 40, short_sha="bbbbbbbb",
                      subject="Tidy up", author="Ada", url="", tickets=[]),
    ]
    return ComponentChange(
        name=name, repo=f"acme/{name}", provider="github",
        old_version="1.0.0", new_version="1.1.0", status=status,
        compare=compare if status == "changed" else None,
        commits=kts,
        mapped_count=sum(1 for k in kts if k.tickets),
        unmapped_count=sum(1 for k in kts if not k.tickets),
        commit_count=len(kts),
        error="tag missing" if status == "error" else "",
    )


def _changeset(components):
    return ReleaseChangeSet(
        release_id=2, version="0.2.0", previous_release_id=1,
        previous_version="0.1.0", umbrella_repo="acme/umbrella",
        umbrella_provider="github", old_tag="v0.1.0", new_tag="v0.2.0",
        components=components,
    )


@pytest.fixture
def run(monkeypatch):
    """Wire run_code_review to fakes; returns hooks to script and observe it."""
    state = {
        "changeset": _changeset([_change()]),
        "prompts": [],       # what the LLM was asked
        "stored": [],        # reports handed to _store_report
        "audited": [],       # audit entries
    }
    monkeypatch.setattr(
        git_changes, "compute_release_changes",
        lambda conn, cfg, rel: state["changeset"],
    )

    class FakeLLM:
        def complete(self, system, prompt, *, max_tokens=4096):
            state["prompts"].append(prompt)
            return "### Findings\n- possible bug in app.py"

    monkeypatch.setattr(code_review, "get_completion_service", lambda cfg: FakeLLM())

    def fake_store(conn, principal, rel, report):
        state["stored"].append(report)
        return {"id": 7, "title": f"Code Review Report v{rel['version']}",
                "status": "DRAFT", "latest_version": len(state["stored"]),
                "doc_type": code_review.REVIEW_DOC_TYPE}

    monkeypatch.setattr(code_review, "_store_report", fake_store)
    monkeypatch.setattr(
        code_review.audit, "record",
        lambda conn, **kw: state["audited"].append(kw),
    )

    class Cfg:
        llm = None

    def invoke():
        return run_code_review(None, Cfg(), FakePrincipal(),
                               {"id": 2, "version": "0.2.0", "product_id": 1})

    return state, invoke


def test_review_lands_as_a_draft_document_and_is_audited(run):
    state, invoke = run
    result = invoke()
    assert result["document"]["status"] == "DRAFT"
    assert result["components_reviewed"] == 1
    assert state["audited"][0]["action"] == "code_review_generated"
    report = state["stored"][0]
    assert "Code Review Report — v0.2.0" in report
    assert "possible bug in app.py" in report
    assert "Advisory" in report


def test_unmapped_commits_are_reported_verbatim(run):
    state, invoke = run
    invoke()
    report = state["stored"][0]
    assert "## Unmapped commits" in report
    assert "`bbbbbbbb` (moda) Tidy up" in report


def test_prompt_carries_commits_tickets_and_the_diff(run):
    state, invoke = run
    invoke()
    prompt = state["prompts"][0]
    assert "aaaaaaaa Fix login (#12) [#12]" in prompt
    assert "bbbbbbbb Tidy up [(no ticket)]" in prompt
    assert "@@ small @@" in prompt


def test_diff_budget_includes_smallest_files_and_names_the_rest(run, monkeypatch):
    state, invoke = run
    monkeypatch.setattr(code_review, "DIFF_BUDGET_CHARS", 100)
    state["changeset"] = _changeset([_change(files=[
        GitFileDiff(path="huge.py", status="modified", additions=999,
                    deletions=0, patch="x" * 500),
        GitFileDiff(path="tiny.py", status="modified", additions=1,
                    deletions=0, patch="y" * 10),
    ])])
    invoke()
    prompt = state["prompts"][0]
    assert "y" * 10 in prompt
    assert "x" * 500 not in prompt
    assert "Files NOT analysed" in prompt
    assert "huge.py" in prompt  # excluded, but named


def test_failed_components_are_listed_as_not_reviewed(run):
    state, invoke = run
    state["changeset"] = _changeset([_change(), _change(name="modb", status="error")])
    result = invoke()
    assert result["components_skipped"] == 1
    report = state["stored"][0]
    assert "## Components not reviewed" in report
    assert "**modb**: tag missing" in report


def test_missing_baseline_refuses_instead_of_reviewing_nothing(run):
    state, invoke = run
    state["changeset"].baseline_missing = "this is the product's first release"
    with pytest.raises(ReviewUnavailable):
        invoke()
    assert state["prompts"] == [] and state["stored"] == []


def test_no_changed_components_refuses_with_a_reason(run):
    state, invoke = run
    state["changeset"] = _changeset([_change(status="unchanged")])
    with pytest.raises(ReviewUnavailable) as exc:
        invoke()
    assert "nothing to review" in str(exc.value)
