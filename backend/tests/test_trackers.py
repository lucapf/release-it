"""Issue-tracker clients: verify they parse the REAL response shapes of the APIs
they call — Jira REST v2 (/search and /issue/{key}, the same shapes the e2e
jira-stub returns) and the GitHub issues API — into ReleaseIT's normalized
issue and issue-detail dicts.
"""
from __future__ import annotations

import pytest

import httpx

import app.integrations.trackers.github as github_mod
import app.integrations.trackers.jira as jira_mod
from app.integrations.trackers import DONE, count_bugs
from app.integrations.trackers.base import (
    TrackerProjectNotFound,
    TrackerUnreachable,
)
from app.integrations.trackers.github import GitHubTracker
from app.integrations.trackers.jira import JiraTracker
from app.services.appconfig import TrackerConfig

# A canonical Jira Cloud/Server REST API v2 `/rest/api/2/search` response. It
# carries the real envelope (expand/startAt/maxResults/total) and richer nested
# objects (id/self/statusCategory/subtask) than the backend needs — the client
# must read its subset and ignore the rest.
REAL_JIRA_SEARCH = {
    "expand": "schema,names",
    "startAt": 0,
    "maxResults": 50,
    "total": 2,
    "issues": [
        {
            "id": "10001",
            "self": "https://jira.example.com/rest/api/2/issue/10001",
            "key": "REL-1",
            "fields": {
                "summary": "crash on save",
                "issuetype": {"id": "1", "name": "Bug", "subtask": False},
                "status": {
                    "id": "10000",
                    "name": "To Do",
                    "statusCategory": {"key": "new", "name": "To Do"},
                },
            },
        },
        {
            "id": "10002",
            "self": "https://jira.example.com/rest/api/2/issue/10002",
            "key": "REL-2",
            "fields": {
                "summary": "add export",
                "issuetype": {"id": "3", "name": "Story"},
                "status": {
                    "id": "10002",
                    "name": "Done",
                    "statusCategory": {"key": "done", "name": "Done"},
                },
            },
        },
    ],
}


class _Resp:
    def __init__(self, data, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_jira_client_parses_real_search_response(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["auth"] = (headers or {}).get("Authorization")
        return _Resp(REAL_JIRA_SEARCH)

    monkeypatch.setattr(jira_mod.httpx, "get", fake_get)

    tracker = JiraTracker(
        TrackerConfig(enabled=True, base_url="https://jira.example.com", token="t0ken")
    )
    issues = tracker.fetch_issues('fixVersion = "1.0.0"')

    # Calls the real Jira search endpoint with the JQL and bearer token.
    assert captured["url"] == "https://jira.example.com/rest/api/2/search"
    assert captured["params"] == {"jql": 'fixVersion = "1.0.0"'}
    assert captured["auth"] == "Bearer t0ken"
    # Normalizes the real response into ReleaseIT's issue shape, with the browse
    # URL an operator opens (derived from the key — Jira's own `self` is a REST
    # endpoint, not a page).
    assert issues == [
        {"key": "REL-1", "type": "Bug", "summary": "crash on save", "status": "To Do",
         "closed": False, "url": "https://jira.example.com/browse/REL-1"},
        {"key": "REL-2", "type": "Story", "summary": "add export", "status": "Done",
         "closed": True, "url": "https://jira.example.com/browse/REL-2"},
    ]


def test_jira_client_returns_empty_when_not_configured():
    assert JiraTracker(TrackerConfig(False, "", "")).fetch_issues("x") == []
    assert JiraTracker(TrackerConfig(True, "", "")).fetch_issues("x") == []


# --- "Is this issue finished?" is Jira's call, not ours ---------------------
def _jira_issues_with_status(monkeypatch, status: dict) -> list[dict]:
    payload = {"issues": [{"key": "REL-1", "fields": {
        "summary": "s", "issuetype": {"name": "Bug"}, "status": status,
    }}]}
    monkeypatch.setattr(
        jira_mod.httpx, "get",
        lambda url, headers=None, params=None, timeout=None: _Resp(payload),
    )
    tracker = JiraTracker(TrackerConfig(True, "https://jira.example.com", "t"))
    return tracker.fetch_issues("x")


def test_closed_follows_the_status_category_not_the_status_name(monkeypatch):
    """A project is free to call its done-status "Resolved", "Shipped", anything.
    Jira groups every status into a *statusCategory*, and that is what says the
    issue is finished.

    Release-It used to decide this itself, by matching the status name against a
    configured CLOSED_BUG_STATUSES list (default "Done"). On a project whose
    done-status was called "Resolved", every issue therefore counted as open
    forever — `no_open_issues` could never be satisfied and the release could
    never be approved. This is that bug.
    """
    resolved = _jira_issues_with_status(
        monkeypatch,
        {"name": "Resolved", "statusCategory": {"key": "done", "name": "Done"}},
    )
    assert resolved[0]["status"] == "Resolved"
    assert resolved[0]["closed"] is True

    # ...and the converse: a status *named* "Done" that Jira does not categorise
    # as done (a project can do this) is still open.
    in_progress = _jira_issues_with_status(
        monkeypatch,
        {"name": "Done", "statusCategory": {"key": "indeterminate", "name": "In Progress"}},
    )
    assert in_progress[0]["closed"] is False


def test_a_status_with_no_category_counts_as_open(monkeypatch):
    """Fail safe. If we cannot tell whether an issue is finished, it must keep
    blocking a guarded transition — never unblock one on no evidence."""
    unknown = _jira_issues_with_status(monkeypatch, {"name": "Done"})
    assert unknown[0]["closed"] is False


# --- Single-issue detail (the on-demand "view details" action) --------------
# A real `GET /rest/api/2/issue/REL-1` response, trimmed to the fields the
# detail view reads plus enough noise to prove the client ignores the rest.
REAL_JIRA_ISSUE = {
    "id": "10001",
    "self": "https://jira.example.com/rest/api/2/issue/10001",
    "key": "REL-1",
    "fields": {
        "summary": "crash on save",
        "description": "Steps:\n1. open\n2. save",
        "issuetype": {"id": "1", "name": "Bug", "subtask": False},
        "status": {
            "id": "10000",
            "name": "To Do",
            "statusCategory": {"key": "new", "name": "To Do"},
        },
        "priority": {"id": "3", "name": "High"},
        "assignee": {"name": "adevs", "displayName": "A. Developer"},
        "reporter": {"name": "qa", "displayName": "Q. Assurance"},
        "labels": ["v1.0.0", "regression"],
        "created": "2025-01-02T10:00:00.000+0000",
        "updated": "2025-01-03T11:30:00.000+0000",
        "watches": {"watchCount": 2},
    },
}


def test_jira_client_fetches_one_issue_in_full(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        return _Resp(REAL_JIRA_ISSUE)

    monkeypatch.setattr(jira_mod.httpx, "get", fake_get)
    tracker = JiraTracker(
        TrackerConfig(enabled=True, base_url="https://jira.example.com", token="t0ken")
    )
    issue = tracker.fetch_issue("REL-1")

    assert captured["url"] == "https://jira.example.com/rest/api/2/issue/REL-1"
    assert issue == {
        "key": "REL-1",
        "type": "Bug",
        "summary": "crash on save",
        "status": "To Do",
        "closed": False,
        "url": "https://jira.example.com/browse/REL-1",
        "description": "Steps:\n1. open\n2. save",
        "assignee": "A. Developer",
        "reporter": "Q. Assurance",
        "priority": "High",
        "labels": ["v1.0.0", "regression"],
        "created_at": "2025-01-02T10:00:00.000+0000",
        "updated_at": "2025-01-03T11:30:00.000+0000",
    }


def test_jira_issue_detail_tolerates_missing_and_non_text_fields(monkeypatch):
    """An unassigned, unprioritized issue on a v3 server (ADF description) still
    yields every field — the description is dropped rather than dumped as a dict."""
    sparse = {"key": "REL-9", "fields": {
        "summary": "no owner",
        "description": {"type": "doc", "content": []},
        "issuetype": {"name": "Task"},
        "status": {"name": "To Do"},
    }}
    monkeypatch.setattr(jira_mod.httpx, "get", lambda *a, **k: _Resp(sparse))

    issue = JiraTracker(TrackerConfig(True, "https://jira.example.com", "t")).fetch_issue("REL-9")

    assert issue["description"] == ""
    assert issue["assignee"] == issue["reporter"] == issue["priority"] == ""
    assert issue["labels"] == []


def test_jira_issue_detail_missing_issue_is_none(monkeypatch):
    monkeypatch.setattr(jira_mod.httpx, "get", lambda *a, **k: _Resp({}, status_code=404))
    tracker = JiraTracker(TrackerConfig(True, "https://jira.example.com", "t"))
    assert tracker.fetch_issue("REL-404") is None
    # Not configured, or no key: nothing to fetch, no call made.
    assert JiraTracker(TrackerConfig(False, "", "")).fetch_issue("REL-1") is None
    assert tracker.fetch_issue("") is None


# A real `GET /repos/acme/app/issues/12` response, trimmed as above.
REAL_GITHUB_ISSUE = {
    "number": 12,
    "html_url": "https://github.com/acme/app/issues/12",
    "title": "crash on save",
    "state": "closed",
    "body": "Steps:\n1. open\n2. save",
    "user": {"login": "reporter1"},
    "assignee": {"login": "dev1"},
    "labels": [{"name": "bug"}, {"name": "regression"}],
    "created_at": "2025-01-02T10:00:00Z",
    "updated_at": "2025-01-03T11:30:00Z",
    "comments": 3,
}


def test_github_client_fetches_one_issue_in_full(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        return _Resp(REAL_GITHUB_ISSUE)

    monkeypatch.setattr(github_mod.httpx, "get", fake_get)
    tracker = GitHubTracker(
        TrackerConfig(enabled=True, base_url="https://api.github.com", token="t0ken")
    )
    # The stored key carries GitHub's '#' prefix; the API wants the bare number.
    issue = tracker.fetch_issue("#12", repo="acme/app")

    assert captured["url"] == "https://api.github.com/repos/acme/app/issues/12"
    assert issue == {
        "key": "#12",
        "type": "bug",
        "summary": "crash on save",
        "status": DONE,
        "closed": True,
        "url": "https://github.com/acme/app/issues/12",
        "description": "Steps:\n1. open\n2. save",
        "assignee": "dev1",
        "reporter": "reporter1",
        "priority": "",  # GitHub has no priority field
        "labels": ["bug", "regression"],
        "created_at": "2025-01-02T10:00:00Z",
        "updated_at": "2025-01-03T11:30:00Z",
    }


def test_github_issue_detail_needs_a_repo_and_a_numeric_key():
    tracker = GitHubTracker(TrackerConfig(True, "https://api.github.com", "t"))
    with pytest.raises(ValueError):
        tracker.fetch_issue("#12", repo="")
    assert tracker.fetch_issue("not-a-number", repo="acme/app") is None
    assert GitHubTracker(TrackerConfig(False, "", "")).fetch_issue("#12") is None


# --- Bug counting (the /bugs/count endpoint's logic) ------------------------
# NOTE: there is no longer a `release_label()` helper. It derived a
# "v<major>.<minor>.<patch>" label that only /bugs/count used, to run its own
# issue query — which is exactly how that endpoint came to disagree with the
# status endpoint about how many bugs a release contained. Both now resolve the
# release's issues through trackers.release_query(); see test_issues.
def test_count_bugs_matches_normalized_type_case_insensitively():
    issues = [
        {"key": "#1", "type": "bug", "summary": "gh bug", "status": "Open"},       # GitHub
        {"key": "REL-1", "type": "Bug", "summary": "jira bug", "status": "To Do"},  # Jira
        {"key": "REL-2", "type": "Story", "summary": "feature", "status": "Done"},
        {"key": "#2", "type": "", "summary": "untyped", "status": "Open"},
    ]
    assert count_bugs(issues) == 2
    assert count_bugs([]) == 0


# --- verify_project: confirm a bound tracker project actually exists ---------
def test_jira_verify_project_hits_project_api_and_accepts_existing(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        return _Resp({"key": "REL", "name": "ReleaseIT"})

    monkeypatch.setattr(jira_mod.httpx, "get", fake_get)
    tracker = JiraTracker(TrackerConfig(True, "https://jira.example.com", "t0ken"))
    tracker.verify_project("REL")  # exists → returns without raising
    assert captured["url"] == "https://jira.example.com/rest/api/2/project/REL"


def test_jira_verify_project_raises_not_found_on_404(monkeypatch):
    monkeypatch.setattr(
        jira_mod.httpx, "get", lambda *a, **k: _Resp({}, status_code=404)
    )
    tracker = JiraTracker(TrackerConfig(True, "https://jira.example.com", "t"))
    with pytest.raises(TrackerProjectNotFound):
        tracker.verify_project("NOPE")


def test_jira_verify_project_raises_unreachable_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(jira_mod.httpx, "get", boom)
    tracker = JiraTracker(TrackerConfig(True, "https://jira.invalid", "t"))
    with pytest.raises(TrackerUnreachable):
        tracker.verify_project("REL")


def test_github_verify_project_hits_repos_api_and_accepts_existing(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        return _Resp({"full_name": "acme/app"})

    monkeypatch.setattr(github_mod.httpx, "get", fake_get)
    tracker = GitHubTracker(TrackerConfig(True, "https://api.github.com", "t0ken"))
    tracker.verify_project("acme/app")
    assert captured["url"] == "https://api.github.com/repos/acme/app"


def test_github_verify_project_raises_not_found_on_404(monkeypatch):
    monkeypatch.setattr(
        github_mod.httpx, "get", lambda *a, **k: _Resp({}, status_code=404)
    )
    tracker = GitHubTracker(TrackerConfig(True, "https://api.github.com", "t"))
    with pytest.raises(TrackerProjectNotFound):
        tracker.verify_project("acme/does-not-exist")


def test_github_verify_project_raises_unreachable_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(github_mod.httpx, "get", boom)
    tracker = GitHubTracker(TrackerConfig(True, "https://api.github.invalid", "t"))
    with pytest.raises(TrackerUnreachable):
        tracker.verify_project("acme/app")
