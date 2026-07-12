"""Jira issue tracker — issues via the Jira REST search API (JQL).

Talks to the configured ``jira_base_url`` (a real Jira, or the e2e jira-stub
which speaks the same REST API). No in-process stub.
"""
from __future__ import annotations

import logging

import httpx

from app.integrations.trackers.base import (
    IssueNotFound,
    MembershipNotEnforceable,
    TrackerProjectNotFound,
    TrackerUnreachable,
    detail,
)
from app.services.appconfig import TrackerConfig

log = logging.getLogger("releaseit.tracker.jira")


def _name(field: dict | None) -> str:
    """The ``name`` of a nested Jira object (issuetype, status, priority)."""
    return (field or {}).get("name", "") or ""


def _closed(status: dict | None) -> bool:
    """Whether Jira considers this issue finished.

    Jira groups every status into one of three *status categories* — ``new``,
    ``indeterminate``, ``done`` — and the category is what carries the meaning;
    the status *name* is just a label a project admin chose. Reading the category
    is what lets a project call its done-status "Resolved" or "Shipped" without
    Release-It having to be told about it.

    A payload with no category at all (an old server, or an incomplete stub) is
    reported as *not* closed: a guarded transition must not be unblocked by an
    issue we cannot prove is finished.
    """
    category = ((status or {}).get("statusCategory") or {}).get("key", "")
    if not category:
        log.warning(
            "Jira status %r carries no statusCategory — treating the issue as open",
            _name(status) or "?",
        )
        return False
    return category.lower() == "done"


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

    def verify_project(self, repo: str) -> None:
        """Confirm the Jira project key ``repo`` exists via the project API."""
        key = (repo or "").strip()
        if not key:
            return
        try:
            resp = httpx.get(
                f"{self._cfg.base_url}/rest/api/2/project/{key}",
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code == 404:
                raise TrackerProjectNotFound(key)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise TrackerUnreachable(str(exc)) from exc

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
                "closed": _closed(fields.get("status")),
                "url": self._browse_url(key),
            })
        return issues

    def set_membership(
        self, key: str, *, mode: str, value: str, member: bool, repo: str = ""
    ) -> None:
        """Add/remove the criteria's label on a Jira issue.

        Jira's own edit verb for this is ``update.labels: [{"add": ...}]`` — a
        *delta*, not a rewrite of the label list. That matters: reading the labels,
        appending one and PUTting the whole array back would silently drop any
        label added by someone else in between, and quietly evict a ticket from
        another release whose criteria is that label.
        """
        if mode != "label":
            raise MembershipNotEnforceable(
                f"this release selects its tickets by {mode}, and a {mode} criteria "
                "cannot be satisfied by editing a ticket. Give the release a label "
                "criteria (e.g. label = v0.0.1) to add and remove tickets this way, "
                "or edit the ticket in Jira directly."
            )
        op = "add" if member else "remove"
        resp = httpx.put(
            f"{self._cfg.base_url}/rest/api/2/issue/{key}",
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"update": {"labels": [{op: value}]}},
            timeout=30,
        )
        if resp.status_code == 404:
            raise IssueNotFound(key)
        resp.raise_for_status()

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
            closed=_closed(fields.get("status")),
            url=self._browse_url(issue.get("key", key)),
            description=_description(fields.get("description")),
            assignee=_person(fields.get("assignee")),
            reporter=_person(fields.get("reporter")),
            priority=_name(fields.get("priority")),
            labels=list(fields.get("labels") or []),
            created_at=fields.get("created", "") or "",
            updated_at=fields.get("updated", "") or "",
        )
