"""Jira issue tracker — issues via the Jira REST search API (JQL).

Talks to the configured ``jira_base_url`` (a real Jira, or the e2e jira-stub
which speaks the same REST API). No in-process stub.
"""
from __future__ import annotations

import logging

import httpx

from app.integrations.trackers.base import detail
from app.services.appconfig import TrackerConfig

log = logging.getLogger("releaseit.tracker.jira")


def _name(field: dict | None) -> str:
    """The ``name`` of a nested Jira object (issuetype, status, priority)."""
    return (field or {}).get("name", "") or ""


def _person(field: dict | None) -> str:
    """A Jira user's human-facing name, falling back to the account name."""
    user = field or {}
    return user.get("displayName") or user.get("name") or ""


def _description(value: object) -> str:
    """REST v2 renders the description as plain text/wiki markup. A v3 server
    answers with an Atlassian Document Format object instead — we have nothing
    to render it with, so show nothing rather than a dumped dict."""
    return value if isinstance(value, str) else ""


class JiraTracker:
    def __init__(self, cfg: TrackerConfig):
        self._cfg = cfg

    def _configured(self) -> bool:
        cfg = self._cfg
        if cfg.enabled and cfg.base_url:
            return True
        log.info(
            "Jira not configured (enabled=%s, base_url set=%s) — no issues",
            cfg.enabled,
            bool(cfg.base_url),
        )
        return False

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._cfg.token}"}

    def _browse_url(self, key: str) -> str:
        """The Jira web page for an issue — what an operator opens."""
        base = self._cfg.base_url.rstrip("/")
        return f"{base}/browse/{key}" if base and key else ""

    def fetch_issues(
        self, query: str, *, repo: str = "", filter_kind: str = ""
    ) -> list[dict]:
        if not self._configured():
            return []
        resp = httpx.get(
            f"{self._cfg.base_url}/rest/api/2/search",
            headers=self._headers(),
            params={"jql": query},
            timeout=30,
        )
        resp.raise_for_status()
        issues = []
        for i in resp.json().get("issues", []):
            fields = i.get("fields", {}) or {}
            key = i.get("key", "")
            issues.append({
                "key": key,
                "type": _name(fields.get("issuetype")) or "Task",
                "summary": fields.get("summary", "") or "",
                "status": _name(fields.get("status")),
                "url": self._browse_url(key),
            })
        return issues

    def fetch_issue(self, key: str, *, repo: str = "") -> dict | None:
        if not self._configured() or not key:
            return None
        resp = httpx.get(
            f"{self._cfg.base_url}/rest/api/2/issue/{key}",
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        issue = resp.json()
        fields = issue.get("fields", {}) or {}
        return detail(
            key=issue.get("key", key),
            type=_name(fields.get("issuetype")) or "Task",
            summary=fields.get("summary", "") or "",
            status=_name(fields.get("status")),
            url=self._browse_url(issue.get("key", key)),
            description=_description(fields.get("description")),
            assignee=_person(fields.get("assignee")),
            reporter=_person(fields.get("reporter")),
            priority=_name(fields.get("priority")),
            labels=list(fields.get("labels") or []),
            created_at=fields.get("created", "") or "",
            updated_at=fields.get("updated", "") or "",
        )
