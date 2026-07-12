"""GitHub issue tracker — issues via the GitHub REST issues API.

Talks to the configured GitHub API (``github_base_url``). No in-process stub:
when GitHub is not enabled/configured there are no issues to report.
"""
from __future__ import annotations

import logging

import httpx

from app.integrations.trackers.base import (
    DONE,
    IssueNotFound,
    MembershipNotEnforceable,
    TrackerProjectNotFound,
    TrackerUnreachable,
    detail,
)
from app.services.appconfig import TrackerConfig

log = logging.getLogger("releaseit.tracker.github")


def _gh_type(labels: list[dict]) -> str:
    names = {(l.get("name") or "").lower() for l in labels}
    for kind in ("bug", "enhancement", "documentation", "feature"):
        if kind in names:
            return kind
    return "issue"


def _issue_number(key: str) -> int | None:
    """The numeric id behind a stored GitHub key ("#12" -> 12)."""
    try:
        return int((key or "").lstrip("#").strip())
    except ValueError:
        return None


class GitHubTracker:
    def __init__(self, cfg: TrackerConfig):
        self._cfg = cfg

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._cfg.token}",
            "Accept": "application/vnd.github+json",
        }

    def _milestone_number(self, repo: str, title: str) -> int | None:
        """Resolve a milestone *title* (e.g. the release version "0.1.0") to its
        numeric id, which is what the issues API filters on. Returns None when no
        milestone with that title exists (open or closed)."""
        resp = httpx.get(
            f"{self._cfg.base_url}/repos/{repo}/milestones",
            headers=self._headers(),
            params={"state": "all", "per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        wanted = title.strip().lower()
        for m in resp.json():
            if (m.get("title") or "").strip().lower() == wanted:
                return m.get("number")
        return None

    def _current_milestone(self, issue_url: str) -> str:
        """The title of the milestone an issue currently sits in, lowercased
        ("" when it is in none)."""
        resp = httpx.get(issue_url, headers=self._headers(), timeout=30)
        if resp.status_code == 404:
            raise IssueNotFound(issue_url.rsplit("/", 1)[-1])
        resp.raise_for_status()
        milestone = resp.json().get("milestone") or {}
        return (milestone.get("title") or "").strip().lower()

    def verify_project(self, repo: str) -> None:
        """Confirm the GitHub repository ``owner/repo`` exists via the repos API."""
        slug = (repo or "").strip()
        if not slug:
            return
        try:
            resp = httpx.get(
                f"{self._cfg.base_url}/repos/{slug}",
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code == 404:
                raise TrackerProjectNotFound(slug)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise TrackerUnreachable(str(exc)) from exc

    def fetch_issues(
        self, query: str, *, repo: str = "", filter_kind: str = ""
    ) -> list[dict]:
        gh = self._cfg
        if not gh.enabled or not gh.base_url:
            log.info(
                "GitHub not configured (enabled=%s, base_url set=%s) — no issues",
                gh.enabled,
                bool(gh.base_url),
            )
            return []
        if not repo:
            raise ValueError("No GitHub repository configured for this product")

        kind = filter_kind or "milestone"
        params: dict = {"state": "all", "per_page": 100}
        if kind == "label":
            if query:
                params["labels"] = query
        else:  # milestone (GitHub's native "issues in a release" grouping)
            number = self._milestone_number(repo, query) if query else None
            if number is None:
                # No such milestone → the release contains no tracked issues yet.
                log.info("GitHub repo=%s milestone=%r not found", repo, query)
                return []
            params["milestone"] = number

        resp = httpx.get(
            f"{gh.base_url}/repos/{repo}/issues",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        issues = []
        for i in resp.json():
            if "pull_request" in i:  # the issues API also returns PRs — skip them
                continue
            closed = i.get("state") == "closed"
            issues.append({
                "key": f"#{i.get('number', '')}",
                "type": _gh_type(i.get("labels", []) or []),
                "summary": i.get("title", ""),
                "status": DONE if closed else "Open",
                "closed": closed,
                "url": i.get("html_url", "") or "",
            })
        return issues

    def set_membership(
        self, key: str, *, mode: str, value: str, member: bool, repo: str = ""
    ) -> None:
        """Add/remove the criteria's label, or set/clear the criteria's milestone.

        Both use GitHub's own membership verbs rather than rewriting the issue: the
        labels sub-resource adds or deletes a single label, and the milestone is a
        single field. Nothing else on the issue is touched.
        """
        if not repo:
            raise ValueError("No GitHub repository configured for this product")
        number = _issue_number(key)
        if number is None:
            raise IssueNotFound(key)
        base = f"{self._cfg.base_url}/repos/{repo}/issues/{number}"

        if mode == "label":
            if member:
                resp = httpx.post(f"{base}/labels", headers=self._headers(),
                                  json={"labels": [value]}, timeout=30)
            else:
                resp = httpx.delete(f"{base}/labels/{value}", headers=self._headers(),
                                    timeout=30)
                # GitHub 404s when the label isn't on the issue. The ticket is
                # already out of the release, which is what was asked for.
                if resp.status_code == 404:
                    return
        elif mode == "milestone":
            if member:
                milestone = self._milestone_number(repo, value)
                if milestone is None:
                    raise MembershipNotEnforceable(
                        f'this release selects its tickets by the milestone "{value}", '
                        f"which does not exist in {repo}. Create the milestone in "
                        "GitHub first, or give the release a label criteria."
                    )
                resp = httpx.patch(base, headers=self._headers(),
                                   json={"milestone": milestone}, timeout=30)
            else:
                # Only clear the milestone if it is *this release's*. An issue
                # sitting in some other milestone is already not in this release,
                # and evicting it from that one would be a change nobody asked for.
                if self._current_milestone(base) != value.strip().lower():
                    return
                resp = httpx.patch(base, headers=self._headers(),
                                   json={"milestone": None}, timeout=30)
        else:
            raise MembershipNotEnforceable(
                f"this release selects its tickets by {mode}, which cannot be "
                "satisfied by editing a ticket."
            )

        if resp.status_code == 404:
            raise IssueNotFound(key)
        resp.raise_for_status()

    def fetch_issue(self, key: str, *, repo: str = "") -> dict | None:
        gh = self._cfg
        if not gh.enabled or not gh.base_url:
            return None
        if not repo:
            raise ValueError("No GitHub repository configured for this product")
        number = _issue_number(key)
        if number is None:
            return None

        resp = httpx.get(
            f"{gh.base_url}/repos/{repo}/issues/{number}",
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        i = resp.json()
        labels = i.get("labels", []) or []
        closed = i.get("state") == "closed"
        return detail(
            key=f"#{i.get('number', number)}",
            type=_gh_type(labels),
            summary=i.get("title", "") or "",
            status=DONE if closed else "Open",
            closed=closed,
            url=i.get("html_url", "") or "",
            description=i.get("body") or "",
            assignee=(i.get("assignee") or {}).get("login", ""),
            reporter=(i.get("user") or {}).get("login", ""),
            labels=[l.get("name", "") for l in labels],
            created_at=i.get("created_at", "") or "",
            updated_at=i.get("updated_at", "") or "",
        )
