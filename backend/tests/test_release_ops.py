"""Release create and transition — `release_ops`.

Two things are enforced here and nowhere else (the REST routes and the LLM
assistant both funnel through this module):

* A release is created *with* the search criteria that says which tickets it
  contains. Without one, every later question about its issues has no defensible
  answer.
* A guarded transition is decided on what the ticketing system says **now**.
  Release-It used to keep a copy of the issues in a `jira_issue` table, refreshed
  by a 10-minute poll, and the gate read that copy — so it could approve a release
  whose last bug had been reopened two minutes earlier. There is no copy any more,
  and these tests hold the gate to the tracker.

No database: the repositories and the tracker are faked, so what is exercised is
release_ops' own ordering and enforcement logic.
"""
from __future__ import annotations

import httpx
import pytest

from app.core.identity import Principal
from app.integrations import trackers
from app.services import appconfig, release_ops, release_status
from app.services.release_ops import ReleaseActionError
from app.services.state_machine import build_state_machine

ROWS = [
    {"name": "Draft", "transitions": [
        {"name": "Ready", "target": "In QA", "roles": ["Developer"], "requires": []},
    ]},
    {"name": "In QA", "transitions": [
        {"name": "Approve", "target": "Approved",
         "roles": ["QA Manager"], "requires": ["no_open_issues"]},
        {"name": "Reject", "target": "Rejected",
         "roles": ["QA Manager"], "requires": []},
    ]},
    {"name": "Rejected", "transitions": []},
    {"name": "Approved", "transitions": []},
]

QA = Principal(subject="qa@example.com", roles={"QA Manager"})
DEV = Principal(subject="dev@example.com", roles={"Developer"})


def _issue(status: str, *, closed: bool) -> dict:
    """One ticket as the tracker reports it.

    The status *name* is deliberately "Resolved" rather than "Done": whether an
    issue is finished is the tracker's `closed` verdict, and nothing in the gate
    may go back to matching status names.
    """
    return {
        "key": "REL-1", "type": "Bug", "summary": "crash on save",
        "status": status, "closed": closed, "url": "",
    }


OPEN_BUG = _issue("In Progress", closed=False)
FIXED_BUG = _issue("Resolved", closed=True)

CFG = appconfig.EffectiveConfig(
    provider="jira",
    jira=appconfig.TrackerConfig(True, "http://jira", ""),
    github=appconfig.TrackerConfig(False, "", ""),
    llm=appconfig.LLMConfig("claude", "", "", "", ""),
)


class World:
    """A release and the tracker's current answer about its issues — which, now
    that nothing is stored, is the only issue state there is."""

    def __init__(self, *, state="In QA", tracker=()):
        self.release = {"id": 1, "product_id": 1, "version": "1.0.0", "state": state}
        self.tracker = list(tracker)          # what the tracker says *now*
        self.tracker_error: Exception | None = None
        self.reads = 0                        # how many times we asked it
        self.audit: list[dict] = []
        self.criteria: tuple[str, str] | None = None
        self.pipelines: list[tuple] = []

    # --- the fakes release_ops talks to ---
    def for_release(self, conn, cfg, rel):
        self.reads += 1
        if self.tracker_error is not None:
            raise self.tracker_error
        return [dict(i) for i in self.tracker]

    def set_state(self, conn, release_id, state):
        self.release["state"] = state
        return dict(self.release)

    def create(self, conn, **kw):
        return {"id": 7, "product_id": kw["product_id"], "version": kw["version"],
                "state": kw["state"], "short_description": kw["short_description"]}

    def save_criteria(self, conn, release_id, mode, value):
        self.criteria = (mode, value)
        return {"release_id": release_id, "filter_mode": mode, "filter_value": value}


@pytest.fixture
def sm():
    return build_state_machine(ROWS)


@pytest.fixture
def world(monkeypatch):
    w = World()

    monkeypatch.setattr(release_ops.repo, "get", lambda conn, rid: dict(w.release))
    monkeypatch.setattr(release_ops.repo, "set_state", w.set_state)
    monkeypatch.setattr(release_ops.repo, "create", w.create)
    monkeypatch.setattr(release_ops.products_repo, "get", lambda conn, pid: {"id": pid})
    monkeypatch.setattr(release_ops.issues_svc, "save_criteria", w.save_criteria)
    # No app_config overrides: each transition's allowed roles come from the graph.
    monkeypatch.setattr(appconfig.repo, "get_all", lambda conn: {})
    monkeypatch.setattr(release_ops.appconfig, "effective", lambda conn: CFG)
    monkeypatch.setattr(release_status.appconfig, "effective", lambda conn: CFG)
    monkeypatch.setattr(release_ops.audit, "record", lambda conn, **kw: w.audit.append(kw))
    # The readiness computation runs for real, over a faked tracker and documents.
    monkeypatch.setattr(release_status.issues_svc, "for_release", w.for_release)
    monkeypatch.setattr(release_status.documents_repo, "present_types", lambda conn, rid: set())
    monkeypatch.setattr(release_status.documents_repo, "approved_types", lambda conn, rid: set())
    return w


# --- The gate asks the tracker, every time ---------------------------------
def test_the_gate_decides_on_the_trackers_current_answer(world, sm):
    """The bug is closed in the tracker, so the approval goes through — with no
    cache to be stale, there is no poll interval to wait out first."""
    world.tracker = [dict(FIXED_BUG)]

    updated = release_ops.apply_transition(None, sm, QA, 1, "Approve")

    assert world.reads == 1, "the gate must ask the tracker before deciding"
    assert updated["state"] == "Approved"


def test_an_open_bug_in_the_tracker_blocks_the_approval(world, sm):
    """The dangerous direction: a bug reopened moments ago. Under the old cache
    the gate could still be holding the tracker's previous answer and approve."""
    world.tracker = [dict(OPEN_BUG)]

    with pytest.raises(ReleaseActionError) as exc:
        release_ops.apply_transition(None, sm, QA, 1, "Approve")

    assert exc.value.status_code == 409
    assert "1 open issue" in exc.value.detail
    assert world.release["state"] == "In QA", "the release must not have moved"


def test_an_unreachable_tracker_refuses_the_transition(world, sm):
    """Fail closed. "We could not check" must never quietly become "the check
    passed" — and with no stored issues, nothing is left to fall back to that
    could make it."""
    world.tracker_error = httpx.ConnectError("connection refused")

    with pytest.raises(ReleaseActionError) as exc:
        release_ops.apply_transition(None, sm, QA, 1, "Approve")

    assert exc.value.status_code == 503
    assert world.release["state"] == "In QA"


def test_an_unconfigured_tracker_refuses_the_transition(world, sm):
    world.tracker_error = trackers.TrackerNotConfigured("jira is not enabled")

    with pytest.raises(ReleaseActionError) as exc:
        release_ops.apply_transition(None, sm, QA, 1, "Approve")

    assert exc.value.status_code == 503


# --- Enforcement order, and what an unguarded transition costs --------------
def test_an_unguarded_transition_does_not_call_the_tracker(world, sm):
    """Reject carries no tracker-backed guard, so it must not pay for a tracker
    round trip — and must still work when the tracker is down. Now that every
    issue read is a network call, this is what stops a broken tracker from
    trapping a release in the workflow."""
    world.tracker_error = httpx.ConnectError("connection refused")

    updated = release_ops.apply_transition(None, sm, QA, 1, "Reject")

    assert world.reads == 0
    assert updated["state"] == "Rejected"


def test_the_role_check_precedes_the_tracker_call(world, sm):
    """A caller who may not perform the transition is rejected before we spend a
    tracker round trip on them."""
    world.tracker = [dict(FIXED_BUG)]

    with pytest.raises(ReleaseActionError) as exc:
        release_ops.apply_transition(None, sm, DEV, 1, "Approve")

    assert exc.value.status_code == 403
    assert world.reads == 0


def test_an_illegal_transition_is_rejected(world, sm):
    world.release["state"] = "Draft"
    with pytest.raises(ReleaseActionError) as exc:
        release_ops.apply_transition(None, sm, QA, 1, "Approve")
    assert exc.value.status_code == 409


# --- The side effects a transition is supposed to have ---------------------
def test_a_successful_transition_is_audited(world, sm):
    world.tracker = [dict(FIXED_BUG)]
    release_ops.apply_transition(None, sm, QA, 1, "Approve", note="ship it")

    entry = [a for a in world.audit if a["action"] == "status_update"]
    assert len(entry) == 1
    assert entry[0]["old_value"] == "In QA"
    assert entry[0]["new_value"] == "Approved"
    assert entry[0]["operator"] == "qa@example.com"
    assert entry[0]["note"] == "ship it"


def test_reaching_approved_triggers_the_install_pipeline(world, sm, monkeypatch):
    world.tracker = [dict(FIXED_BUG)]
    monkeypatch.setattr(release_ops.settings, "gitlab_enabled", True)

    class Runner:
        def trigger(self, release_id, ref, variables):
            world.pipelines.append((release_id, ref, variables))

    monkeypatch.setattr(release_ops, "get_runner", lambda name: Runner())

    release_ops.apply_transition(None, sm, QA, 1, "Approve")
    assert world.pipelines == [(1, "1.0.0", {"version": "1.0.0"})]


def test_a_rejected_transition_triggers_no_pipeline(world, sm, monkeypatch):
    world.tracker = [dict(OPEN_BUG)]
    monkeypatch.setattr(release_ops.settings, "gitlab_enabled", True)
    monkeypatch.setattr(
        release_ops, "get_runner",
        lambda name: pytest.fail("a blocked transition must not trigger the pipeline"),
    )

    with pytest.raises(ReleaseActionError):
        release_ops.apply_transition(None, sm, QA, 1, "Approve")


# --- Creating a release: the criteria comes with it ------------------------
def test_create_release_stores_the_search_criteria(world, sm):
    """The criteria is how every later question about this release's issues is put
    to the tracker, so it is recorded with the release and audited — changing it
    moves the goalposts of the readiness gate."""
    rel = release_ops.create_release(
        None, sm, DEV, product_id=1, version="0.0.1",
        filter_mode="label", filter_value="v0.0.1",
    )

    assert rel["state"] == sm.initial_state
    assert world.criteria == ("label", "v0.0.1")
    criteria_entries = [a for a in world.audit if a["action"] == "issue_criteria"]
    assert len(criteria_entries) == 1
    assert criteria_entries[0]["new_value"] == "label = v0.0.1"


def test_create_release_rejects_a_criteria_the_tracker_cannot_answer(world, sm):
    """Jira has no milestones. Storing this would leave the release pointing at a
    question its tracker cannot be asked; quietly falling back to the provider
    default would attach it to tickets nobody chose."""
    with pytest.raises(ReleaseActionError) as exc:
        release_ops.create_release(
            None, sm, DEV, product_id=1, version="0.0.1",
            filter_mode="milestone", filter_value="0.0.1",
        )

    assert exc.value.status_code == 422
    assert world.criteria is None


def test_create_release_rejects_an_empty_criteria(world, sm):
    """"Everything with label ''" is not a definition of a release's contents."""
    with pytest.raises(ReleaseActionError) as exc:
        release_ops.create_release(
            None, sm, DEV, product_id=1, version="0.0.1",
            filter_mode="label", filter_value="",
        )
    assert exc.value.status_code == 422
