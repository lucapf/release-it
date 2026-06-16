"""Jira integration — fetch stories/bugs for a release (stubbed by default)."""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger("releaseit.jira")


def fetch_issues(jql: str) -> list[dict]:
    """Return issues matching a JQL query. Stubbed when Jira is disabled.

    Each issue is a dict with ``key``, ``type``, ``summary`` and ``status``.
    The stub derives a small, deterministic result set from the query so the
    filter-by-label / custom-query UX is exercisable without a real Jira.
    """
    if not settings.jira_enabled:
        log.info("[stub] Jira query: %s", jql)
        return _stub_issues(jql)
    resp = httpx.get(
        f"{settings.jira_base_url}/rest/api/2/search",
        headers={"Authorization": f"Bearer {settings.jira_token}"},
        params={"jql": jql},
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


def _stub_issues(jql: str) -> list[dict]:
    """Deterministic sample issues. A short, stable "project key" is derived from
    the query so different labels/queries return visibly different issue sets."""
    seed = "".join(c for c in jql.upper() if c.isalnum())[:3] or "REL"
    return [
        {"key": f"{seed}-101", "type": "Story", "summary": f"Implement feature for: {jql}", "status": "Done"},
        {"key": f"{seed}-102", "type": "Story", "summary": "Add audit logging to release flow", "status": "In Progress"},
        {"key": f"{seed}-103", "type": "Bug", "summary": "Fix transition validation off-by-one", "status": "Done"},
        {"key": f"{seed}-104", "type": "Task", "summary": "Update deployment Helm chart", "status": "To Do"},
    ]
