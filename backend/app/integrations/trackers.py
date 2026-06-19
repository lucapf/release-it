"""Issue-tracker integrations — pluggable, selected by runtime configuration.

Two providers are supported, switchable via the configuration page:
  * Jira   — issues via the Jira REST search API (JQL).
  * GitHub — issues via the GitHub REST issues API.

Both are stubbed when their integration is disabled, so the whole flow is
exercisable without external systems. The stub is *stateful with respect to a
refresh*: the first sync of a release returns a mix of open/closed issues, and
any subsequent sync ("refresh") returns every issue as Done — simulating the
work being completed over time.
"""
from __future__ import annotations

import logging

import httpx

from app.services.appconfig import EffectiveConfig

log = logging.getLogger("releaseit.tracker")

DONE = "Done"


def _seed(query: str) -> str:
    return "".join(c for c in (query or "").upper() if c.isalnum())[:3] or "REL"


def _all_done(issues: list[dict]) -> list[dict]:
    return [{**i, "status": DONE} for i in issues]


# --- Jira -------------------------------------------------------------------
def _jira_stub(query: str, refresh: bool) -> list[dict]:
    seed = _seed(query)
    issues = [
        {"key": f"{seed}-101", "type": "Story", "summary": f"Implement feature for: {query}", "status": "Done"},
        {"key": f"{seed}-102", "type": "Story", "summary": "Add audit logging to release flow", "status": "In Progress"},
        {"key": f"{seed}-103", "type": "Bug", "summary": "Fix transition validation off-by-one", "status": "In Progress"},
        {"key": f"{seed}-104", "type": "Task", "summary": "Update deployment Helm chart", "status": "To Do"},
    ]
    return _all_done(issues) if refresh else issues


def _jira_fetch(cfg: EffectiveConfig, query: str, refresh: bool) -> list[dict]:
    jira = cfg.jira
    if not jira.enabled:
        log.info("[stub] Jira query=%s refresh=%s", query, refresh)
        return _jira_stub(query, refresh)
    resp = httpx.get(
        f"{jira.base_url}/rest/api/2/search",
        headers={"Authorization": f"Bearer {jira.token}"},
        params={"jql": query},
        timeout=30,
    )
    resp.raise_for_status()
    return [
        {
            "key": i.get("key", ""),
            "type": (i.get("fields", {}).get("issuetype", {}) or {}).get("name", "Task"),
            "summary": i.get("fields", {}).get("summary", ""),
            "status": (i.get("fields", {}).get("status", {}) or {}).get("name", ""),
        }
        for i in resp.json().get("issues", [])
    ]


# --- GitHub -----------------------------------------------------------------
def _github_stub(query: str, refresh: bool) -> list[dict]:
    seed = _seed(query)
    issues = [
        {"key": f"#{seed}-12", "type": "enhancement", "summary": f"Support {query}", "status": "Done"},
        {"key": f"#{seed}-13", "type": "bug", "summary": "Crash on empty release notes", "status": "Open"},
        {"key": f"#{seed}-14", "type": "bug", "summary": "Wrong state badge colour", "status": "Open"},
        {"key": f"#{seed}-15", "type": "documentation", "summary": "Document the install steps", "status": "Open"},
    ]
    return _all_done(issues) if refresh else issues


def _gh_type(labels: list[dict]) -> str:
    names = {(l.get("name") or "").lower() for l in labels}
    for kind in ("bug", "enhancement", "documentation", "feature"):
        if kind in names:
            return kind
    return "issue"


def _gh_headers(gh) -> dict:
    return {
        "Authorization": f"Bearer {gh.token}",
        "Accept": "application/vnd.github+json",
    }


def _github_milestone_number(gh, repo: str, title: str) -> int | None:
    """Resolve a milestone *title* (e.g. the release version "0.1.0") to its
    numeric id, which is what the issues API filters on. Returns None when no
    milestone with that title exists (open or closed)."""
    resp = httpx.get(
        f"{gh.base_url}/repos/{repo}/milestones",
        headers=_gh_headers(gh),
        params={"state": "all", "per_page": 100},
        timeout=30,
    )
    resp.raise_for_status()
    wanted = title.strip().lower()
    for m in resp.json():
        if (m.get("title") or "").strip().lower() == wanted:
            return m.get("number")
    return None


def _github_fetch(
    cfg: EffectiveConfig, repo: str, query: str, filter_kind: str, refresh: bool
) -> list[dict]:
    gh = cfg.github
    if not gh.enabled:
        log.info("[stub] GitHub repo=%s kind=%s query=%s refresh=%s", repo, filter_kind, query, refresh)
        return _github_stub(query, refresh)
    if not repo:
        raise ValueError("No GitHub repository configured for this product")

    params: dict = {"state": "all", "per_page": 100}
    if filter_kind == "label":
        if query:
            params["labels"] = query
    else:  # milestone (GitHub's native "issues in a release" grouping)
        number = _github_milestone_number(gh, repo, query) if query else None
        if number is None:
            # No such milestone → the release contains no tracked issues yet.
            log.info("GitHub repo=%s milestone=%r not found", repo, query)
            return []
        params["milestone"] = number

    resp = httpx.get(
        f"{gh.base_url}/repos/{repo}/issues",
        headers=_gh_headers(gh),
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    issues = []
    for i in resp.json():
        if "pull_request" in i:  # the issues API also returns PRs — skip them
            continue
        issues.append({
            "key": f"#{i.get('number', '')}",
            "type": _gh_type(i.get("labels", []) or []),
            "summary": i.get("title", ""),
            "status": DONE if i.get("state") == "closed" else "Open",
        })
    return issues


# --- Dispatch ---------------------------------------------------------------
def fetch_issues(
    cfg: EffectiveConfig,
    query: str,
    *,
    repo: str = "",
    filter_kind: str = "",
    previous: list[dict] | None = None,
) -> list[dict]:
    """Fetch issues from the active tracker.

    ``query`` is the resolved filter value; ``filter_kind`` selects how it is
    interpreted (GitHub: "milestone" (default) or "label"; Jira queries are
    always JQL). ``repo`` is the product's GitHub "owner/repo". ``previous`` is
    the release's currently-cached issues; when non-empty the (stubbed) trackers
    treat the call as a refresh and report everything as Done."""
    refresh = bool(previous)
    if cfg.provider == "github":
        return _github_fetch(cfg, repo, query, filter_kind or "milestone", refresh)
    return _jira_fetch(cfg, query, refresh)
