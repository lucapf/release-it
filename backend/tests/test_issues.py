"""A release's issues: the stored criteria, and the query it becomes.

Release-It stores no issues — only the criteria that says which tickets belong to
a release. What is worth testing about that criteria is (a) that it is validated
against the tracker that will have to answer it, and (b) that every caller turns
it into the *same* query, so the issue list, the bug count and the readiness gate
can never be looking at different sets of tickets.

No database and no network: the criteria resolver is pure, and the tracker is
faked where one is needed.
"""
from __future__ import annotations

import pytest

from app.integrations import trackers
from app.services import appconfig
from app.services import issues as issues_svc


def _cfg(provider: str, *, enabled: bool = True, base_url: str = "http://t") -> appconfig.EffectiveConfig:
    tracker = appconfig.TrackerConfig(enabled=enabled, base_url=base_url, token="")
    llm = appconfig.LLMConfig("claude", "", "", "", "")
    return appconfig.EffectiveConfig(provider=provider, jira=tracker, github=tracker, llm=llm)


REL = {"id": 1, "version": "1.2.0"}


def _q(cfg, saved: dict | None):
    """release_query() as a release's stored criteria reaches it."""
    saved = saved or {}
    return trackers.release_query(
        cfg, REL,
        mode=saved.get("filter_mode", "") or "",
        value=saved.get("filter_value", "") or "",
    )


# --- The criteria an operator may choose -----------------------------------
def test_criteria_must_be_one_the_active_tracker_can_answer():
    """A criteria is a question put to the ticketing system, so it has to be one
    that system can answer: JQL means nothing to GitHub, milestones mean nothing
    to Jira. Rejected outright — the alternative is silently falling back to the
    provider default and searching for tickets nobody asked for."""
    with pytest.raises(issues_svc.IssueCriteriaError):
        issues_svc.validate_criteria(_cfg("github"), "jql", "project = REL")
    with pytest.raises(issues_svc.IssueCriteriaError):
        issues_svc.validate_criteria(_cfg("jira"), "milestone", "1.2.0")

    assert issues_svc.validate_criteria(_cfg("github"), "label", "v0.0.1") == ("label", "v0.0.1")
    assert issues_svc.validate_criteria(_cfg("jira"), "jql", "project = REL") == ("jql", "project = REL")


def test_a_criteria_without_a_value_is_rejected():
    """"Everything with label ''" is not a definition of a release's contents."""
    with pytest.raises(issues_svc.IssueCriteriaError):
        issues_svc.validate_criteria(_cfg("github"), "label", "   ")
    with pytest.raises(issues_svc.IssueCriteriaError):
        issues_svc.validate_criteria(_cfg("jira"), "", "")


def test_criteria_is_normalized():
    mode, value = issues_svc.validate_criteria(_cfg("github"), "  LABEL ", "  v0.0.1  ")
    assert (mode, value) == ("label", "v0.0.1")


# --- The query that criteria becomes ---------------------------------------
def test_query_honours_the_stored_criteria_github():
    cfg = _cfg("github")
    assert _q(cfg, {"filter_mode": "label", "filter_value": "v1.2.0"}) == ("v1.2.0", "label")
    assert _q(cfg, {"filter_mode": "milestone", "filter_value": "M1"}) == ("M1", "milestone")
    # A release created before criteria were stored -> the provider's native
    # release grouping, a milestone named after the version.
    assert _q(cfg, None) == ("1.2.0", "milestone")


def test_query_honours_the_stored_criteria_jira():
    cfg = _cfg("jira")
    assert _q(cfg, {"filter_mode": "jql", "filter_value": "project = REL"}) == ("project = REL", "jql")
    assert _q(cfg, {"filter_mode": "label", "filter_value": "2025-Q3"}) == ('labels = "2025-Q3"', "jql")
    assert _q(cfg, None) == ('fixVersion = "1.2.0"', "jql")


def test_jql_literals_are_escaped():
    """A criteria value cannot break out of the JQL string literal it lands in.
    `labels = "a" OR key = "X-1"` would otherwise be a query injection."""
    cfg = _cfg("jira")
    query, kind = _q(cfg, {"filter_mode": "label", "filter_value": 'a" OR key = "X-1'})
    assert kind == "jql"
    assert query == 'labels = "a\\" OR key = \\"X-1"'


@pytest.mark.parametrize("provider", ["jira", "github"])
def test_one_definition_of_a_releases_issues(provider):
    """The issue list, the bug count and the readiness gate must resolve the
    *same* set of tickets for a release. They used to each build their own query —
    the bug count filtered on a `v<x.y.z>` label while the sync filtered on
    fixVersion/milestone — so one release could report two different bug counts
    depending on which endpoint you asked."""
    cfg = _cfg(provider)
    saved = {"filter_mode": "label", "filter_value": "2025-Q3"}
    assert _q(cfg, saved) == trackers.release_query(cfg, REL, mode="label", value="2025-Q3")
    assert _q(cfg, None) == trackers.release_query(cfg, REL)


# --- Asking the tracker -----------------------------------------------------
def test_require_configured_rejects_a_disabled_tracker():
    """"We could not ask the tracker" must not be answerable with an empty issue
    list — that reads as "there are no open issues" to a release gate."""
    with pytest.raises(trackers.TrackerNotConfigured):
        trackers.require_configured(_cfg("jira", enabled=False))
    with pytest.raises(trackers.TrackerNotConfigured):
        trackers.require_configured(_cfg("github", base_url=""))
    trackers.require_configured(_cfg("jira"))  # configured -> returns normally


def test_reading_a_releases_issues_always_asks_the_tracker(monkeypatch):
    """The point of the whole change: there is no stored issue list, so every read
    is a question to the ticketing system. Two reads of the same release ask
    twice, and each one gets whatever the tracker says at that moment."""
    calls: list[str] = []
    answers = [
        [{"key": "REL-1", "type": "Bug", "summary": "crash", "status": "Open", "closed": False, "url": ""}],
        [{"key": "REL-1", "type": "Bug", "summary": "crash", "status": "Resolved", "closed": True, "url": ""}],
    ]

    def fetch(cfg, query, *, repo="", filter_kind=""):
        calls.append(query)
        return answers[len(calls) - 1]

    monkeypatch.setattr(issues_svc.trackers, "fetch_issues", fetch)
    monkeypatch.setattr(issues_svc.products_repo, "get", lambda conn, pid: {"tracker_repo": "acme/app"})
    monkeypatch.setattr(issues_svc.filters_repo, "get",
                        lambda conn, rid: {"filter_mode": "label", "filter_value": "v0.0.1"})
    cfg = _cfg("github")
    rel = {"id": 1, "product_id": 1, "version": "1.2.0"}

    first = issues_svc.for_release(None, cfg, rel)
    second = issues_svc.for_release(None, cfg, rel)

    assert calls == ["v0.0.1", "v0.0.1"], "each read must go to the tracker"
    assert first[0]["closed"] is False
    assert second[0]["closed"] is True, "the second read reflects the tracker's new answer"


def test_github_without_a_repository_refuses_to_report_no_issues(monkeypatch):
    """With no repository bound there is nothing to query. Returning "no issues"
    here would tell a readiness gate the release is clean."""
    monkeypatch.setattr(issues_svc.products_repo, "get", lambda conn, pid: {"tracker_repo": ""})
    with pytest.raises(trackers.TrackerNotConfigured):
        issues_svc.for_release(None, _cfg("github"), {"id": 1, "product_id": 1, "version": "1.0.0"})
