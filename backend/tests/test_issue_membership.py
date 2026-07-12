"""Adding and removing a ticket — which means editing the ticket, not our records.

Release-It stores no membership: a ticket is in a release because it *matches the
release's criteria*. So "add REL-1 to v0.0.1" can only mean one thing — edit REL-1
in the ticketing system until it matches, i.e. put the label v0.0.1 on it. These
tests pin down what that edit is per tracker, and what happens when the criteria is
one no edit can satisfy.

The tracker's HTTP layer is faked; everything above it is the real code.
"""
from __future__ import annotations

import pytest

from app.integrations.trackers import github as gh_mod
from app.integrations.trackers import jira as jira_mod
from app.integrations.trackers.base import IssueNotFound, MembershipNotEnforceable
from app.services import appconfig
from app.services import issues as issues_svc


class Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP {self.status_code}")


class Calls(list):
    """Every HTTP call the tracker made, as (method, url, json)."""

    def record(self, method):
        def call(url, **kw):
            self.append((method, url, kw.get("json")))
            return self.response(method, url, kw)
        return call

    response = staticmethod(lambda *a, **k: Resp())


CFG = appconfig.TrackerConfig(enabled=True, base_url="http://tracker", token="t")


# --- Jira: the criteria's label goes on (and off) the ticket ----------------
def test_jira_add_puts_the_criteria_label_on_the_ticket(monkeypatch):
    calls = Calls()
    monkeypatch.setattr(jira_mod.httpx, "put", calls.record("PUT"))

    jira_mod.JiraTracker(CFG).set_membership(
        "REL-1", mode="label", value="v0.0.1", member=True
    )

    method, url, body = calls[0]
    assert (method, url) == ("PUT", "http://tracker/rest/api/2/issue/REL-1")
    # Jira's own delta verb, not a rewrite of the label array: reading the labels
    # and PUTting a new list back would drop any label added concurrently — and
    # could evict the ticket from another release whose criteria is that label.
    assert body == {"update": {"labels": [{"add": "v0.0.1"}]}}


def test_jira_remove_takes_the_criteria_label_off_the_ticket(monkeypatch):
    calls = Calls()
    monkeypatch.setattr(jira_mod.httpx, "put", calls.record("PUT"))

    jira_mod.JiraTracker(CFG).set_membership(
        "REL-1", mode="label", value="v0.0.1", member=False
    )

    assert calls[0][2] == {"update": {"labels": [{"remove": "v0.0.1"}]}}


def test_jira_refuses_when_the_criteria_is_a_jql_query(monkeypatch):
    """`project = REL AND priority = High AND sprint in openSprints()` has no single
    edit behind it. Guessing at one would rewrite fields nobody mentioned, so the
    operator is told to give the release a label criteria instead."""
    monkeypatch.setattr(jira_mod.httpx, "put",
                        lambda *a, **k: pytest.fail("must not edit the ticket"))

    with pytest.raises(MembershipNotEnforceable) as exc:
        jira_mod.JiraTracker(CFG).set_membership(
            "REL-1", mode="jql", value="project = REL", member=True
        )
    assert "label" in str(exc.value)


def test_jira_reports_a_missing_ticket(monkeypatch):
    monkeypatch.setattr(jira_mod.httpx, "put", lambda *a, **k: Resp(404))
    with pytest.raises(IssueNotFound):
        jira_mod.JiraTracker(CFG).set_membership(
            "REL-9", mode="label", value="v0.0.1", member=True
        )


# --- GitHub: labels and milestones -----------------------------------------
def test_github_add_posts_the_label_to_the_issue(monkeypatch):
    calls = Calls()
    monkeypatch.setattr(gh_mod.httpx, "post", calls.record("POST"))

    gh_mod.GitHubTracker(CFG).set_membership(
        "#12", mode="label", value="v0.0.1", member=True, repo="acme/app"
    )

    method, url, body = calls[0]
    assert (method, url) == ("POST", "http://tracker/repos/acme/app/issues/12/labels")
    assert body == {"labels": ["v0.0.1"]}


def test_github_removing_a_label_the_issue_does_not_have_is_not_an_error(monkeypatch):
    """GitHub 404s when the label isn't on the issue. The ticket is already out of
    the release — which is exactly what the caller asked for."""
    monkeypatch.setattr(gh_mod.httpx, "delete", lambda *a, **k: Resp(404))

    gh_mod.GitHubTracker(CFG).set_membership(
        "#12", mode="label", value="v0.0.1", member=False, repo="acme/app"
    )  # returns normally


def test_github_add_sets_the_milestone(monkeypatch):
    calls = Calls()
    monkeypatch.setattr(gh_mod.httpx, "get",
                        lambda *a, **k: Resp(200, [{"title": "0.1.0", "number": 7}]))
    monkeypatch.setattr(gh_mod.httpx, "patch", calls.record("PATCH"))

    gh_mod.GitHubTracker(CFG).set_membership(
        "#12", mode="milestone", value="0.1.0", member=True, repo="acme/app"
    )

    assert calls[0][2] == {"milestone": 7}


def test_github_add_refuses_when_the_milestone_does_not_exist(monkeypatch):
    monkeypatch.setattr(gh_mod.httpx, "get", lambda *a, **k: Resp(200, []))
    monkeypatch.setattr(gh_mod.httpx, "patch",
                        lambda *a, **k: pytest.fail("must not edit the issue"))

    with pytest.raises(MembershipNotEnforceable):
        gh_mod.GitHubTracker(CFG).set_membership(
            "#12", mode="milestone", value="0.1.0", member=True, repo="acme/app"
        )


def test_github_remove_leaves_a_different_milestone_alone(monkeypatch):
    """The issue is in someone else's milestone, so it is already not in this
    release. Clearing that milestone would evict it from a release nobody named."""
    monkeypatch.setattr(gh_mod.httpx, "get",
                        lambda *a, **k: Resp(200, {"milestone": {"title": "0.2.0"}}))
    monkeypatch.setattr(gh_mod.httpx, "patch",
                        lambda *a, **k: pytest.fail("must not touch another milestone"))

    gh_mod.GitHubTracker(CFG).set_membership(
        "#12", mode="milestone", value="0.1.0", member=False, repo="acme/app"
    )  # returns normally, having changed nothing


def test_github_remove_clears_this_releases_milestone(monkeypatch):
    calls = Calls()
    monkeypatch.setattr(gh_mod.httpx, "get",
                        lambda *a, **k: Resp(200, {"milestone": {"title": "0.1.0"}}))
    monkeypatch.setattr(gh_mod.httpx, "patch", calls.record("PATCH"))

    gh_mod.GitHubTracker(CFG).set_membership(
        "#12", mode="milestone", value="0.1.0", member=False, repo="acme/app"
    )

    assert calls[0][2] == {"milestone": None}


# --- The service: the edit is only a success if the release actually changed --
def _cfg(provider="jira"):
    tracker = appconfig.TrackerConfig(enabled=True, base_url="http://t", token="")
    return appconfig.EffectiveConfig(
        provider=provider, jira=tracker, github=tracker,
        llm=appconfig.LLMConfig("claude", "", "", "", ""),
    )


REL = {"id": 1, "product_id": 1, "version": "0.0.1"}


def _issue(key):
    return {"key": key, "type": "Bug", "summary": "s", "status": "Open",
            "closed": False, "url": ""}


@pytest.fixture
def tracker(monkeypatch):
    """A tracker whose issue set the edit is expected to change."""
    state = {"issues": [], "edits": []}

    def set_membership(cfg, key, *, mode, value, member, repo=""):
        state["edits"].append((key, mode, value, member))

    monkeypatch.setattr(issues_svc.trackers, "set_membership", set_membership)
    monkeypatch.setattr(issues_svc.trackers, "fetch_issues",
                        lambda cfg, q, **kw: [dict(i) for i in state["issues"]])
    monkeypatch.setattr(issues_svc.products_repo, "get",
                        lambda conn, pid: {"tracker_repo": "acme/app"})
    monkeypatch.setattr(issues_svc.filters_repo, "get",
                        lambda conn, rid: {"filter_mode": "label", "filter_value": "v0.0.1"})
    return state


def test_adding_a_ticket_edits_it_to_match_the_criteria(tracker):
    tracker["issues"] = [_issue("REL-1")]  # the tracker now returns it for the release

    result = issues_svc.set_membership(None, _cfg(), REL, "REL-1", member=True)

    assert tracker["edits"] == [("REL-1", "label", "v0.0.1", True)]
    assert result["member"] is True
    assert result["criteria"] == "label = v0.0.1"


def test_an_edit_that_leaves_the_release_unchanged_is_not_reported_as_success(tracker):
    """The tracker accepted the edit, but the release's own query still does not
    return the ticket. Reporting "added" here would be a claim the issue list is
    about to contradict — so the result is read back and the mismatch surfaced."""
    tracker["issues"] = []  # the release still doesn't contain it

    with pytest.raises(issues_svc.IssueCriteriaError) as exc:
        issues_svc.set_membership(None, _cfg(), REL, "REL-1", member=True)

    assert "still does not contain it" in str(exc.value)


def test_removing_a_ticket_edits_it_to_stop_matching(tracker):
    tracker["issues"] = []  # gone from the release after the edit

    result = issues_svc.set_membership(None, _cfg(), REL, "REL-1", member=False)

    assert tracker["edits"] == [("REL-1", "label", "v0.0.1", False)]
    assert result["member"] is False


def test_a_release_with_no_criteria_has_nothing_to_edit_a_ticket_to_match(monkeypatch):
    monkeypatch.setattr(issues_svc.filters_repo, "get", lambda conn, rid: None)
    monkeypatch.setattr(issues_svc.products_repo, "get", lambda conn, pid: {"tracker_repo": ""})
    monkeypatch.setattr(issues_svc.trackers, "set_membership",
                        lambda *a, **k: pytest.fail("must not edit anything"))

    with pytest.raises(issues_svc.IssueCriteriaError):
        issues_svc.set_membership(None, _cfg("jira"), REL, "REL-1", member=True)
