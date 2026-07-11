"""Issue-tracker integrations — pluggable, selected by runtime configuration.

Each provider is implemented in its own module behind the common
:class:`IssueTracker` interface (see ``base.py``):

  * Jira   — ``jira.JiraTracker``   (Jira REST search API, JQL)
  * GitHub — ``github.GitHubTracker`` (GitHub REST issues API)

There are no in-process stubs: a tracker calls its real backing service and
returns an empty list when it is not configured. For tests, point the Jira
tracker at the external jira-stub (a Jira-compatible server) via configuration.
"""
from __future__ import annotations

import re

from app.integrations.trackers.base import (
    DONE,
    IssueTracker,
    TrackerError,
    TrackerProjectNotFound,
    TrackerUnreachable,
)
from app.integrations.trackers.github import GitHubTracker
from app.integrations.trackers.jira import JiraTracker
from app.services.appconfig import EffectiveConfig

__all__ = [
    "DONE", "IssueTracker", "JiraTracker", "GitHubTracker",
    "TrackerError", "TrackerProjectNotFound", "TrackerUnreachable",
    "get_tracker", "fetch_issues", "fetch_issue", "verify_project",
    "release_label", "count_bugs",
]

_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def release_label(version: str) -> str:
    """The tracker label identifying a release: ``v<major>.<minor>.<patch>``
    (e.g. ``v0.0.1``). Tolerates a leading 'v' or extra text in the stored
    version; falls back to ``v<version>`` when it is not semver-shaped."""
    m = _SEMVER.search(version or "")
    if m:
        return "v{}.{}.{}".format(*m.groups())
    return f"v{(version or '').strip().lstrip('vV')}"


def count_bugs(issues: list[dict]) -> int:
    """How many of the (normalized) issues are bugs. Trackers normalize the
    type field: GitHub label 'bug' -> "bug", Jira issuetype -> e.g. "Bug"."""
    return sum(1 for i in issues if (i.get("type") or "").strip().lower() == "bug")


def get_tracker(cfg: EffectiveConfig) -> IssueTracker:
    """The tracker for the active provider, configured from ``cfg``."""
    if cfg.provider == "github":
        return GitHubTracker(cfg.github)
    return JiraTracker(cfg.jira)


def fetch_issues(
    cfg: EffectiveConfig, query: str, *, repo: str = "", filter_kind: str = ""
) -> list[dict]:
    """Fetch the issues contained in a release from the active tracker."""
    return get_tracker(cfg).fetch_issues(query, repo=repo, filter_kind=filter_kind)


def fetch_issue(cfg: EffectiveConfig, key: str, *, repo: str = "") -> dict | None:
    """Fetch one issue in full from the active tracker, or None when it is gone."""
    return get_tracker(cfg).fetch_issue(key, repo=repo)


def verify_project(cfg: EffectiveConfig, repo: str) -> None:
    """Confirm ``repo`` exists on the active tracker. Raises
    :class:`TrackerProjectNotFound` or :class:`TrackerUnreachable` otherwise."""
    get_tracker(cfg).verify_project(repo)
