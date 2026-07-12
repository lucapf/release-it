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

from app.integrations.trackers.base import (
    DONE,
    IssueNotFound,
    IssueTracker,
    MembershipNotEnforceable,
    TrackerError,
    TrackerNotConfigured,
    TrackerProjectNotFound,
    TrackerUnreachable,
)
from app.integrations.trackers.github import GitHubTracker
from app.integrations.trackers.jira import JiraTracker
from app.services.appconfig import EffectiveConfig, TrackerConfig

__all__ = [
    "DONE", "IssueTracker", "JiraTracker", "GitHubTracker",
    "TrackerError", "TrackerNotConfigured", "TrackerProjectNotFound",
    "TrackerUnreachable", "MembershipNotEnforceable", "IssueNotFound",
    "get_tracker", "active_config", "require_configured",
    "fetch_issues", "fetch_issue", "verify_project", "set_membership",
    "release_query", "count_bugs",
]


def count_bugs(issues: list[dict]) -> int:
    """How many of the (normalized) issues are bugs. Trackers normalize the
    type field: GitHub label 'bug' -> "bug", Jira issuetype -> e.g. "Bug"."""
    return sum(1 for i in issues if (i.get("type") or "").strip().lower() == "bug")


def _jql_literal(value: str) -> str:
    """``value`` as a quoted JQL string literal, backslash-escaping the
    characters that would otherwise close it early."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def release_query(
    cfg: EffectiveConfig, release: dict, *, mode: str = "", value: str = ""
) -> tuple[str, str]:
    """The definition of "the issues contained in this release", as
    ``(query, filter_kind)`` for the active tracker.

    There is exactly one of these. The scheduled sync, the manual sync and the
    bug count all resolve the release's issue set through this function, so they
    cannot disagree about which issues a release contains — they used to, and a
    release could report a different bug count depending on which endpoint you
    asked.

    ``mode``/``value`` are an explicit filter override (a saved sync filter, or
    the one supplied on a manual sync). With no override, each provider falls
    back to its native "issues in a release" grouping: a GitHub/GitLab milestone
    named after the version, or Jira's ``fixVersion``.
    """
    value = (value or "").strip()

    if cfg.provider == "github":
        if value and mode in {"label", "milestone"}:
            return value, mode
        return release["version"], "milestone"

    # Jira — always JQL.
    if value and mode == "jql":
        return value, "jql"
    if value and mode == "label":
        return f"labels = {_jql_literal(value)}", "jql"
    return f"fixVersion = {_jql_literal(release['version'])}", "jql"


def get_tracker(cfg: EffectiveConfig) -> IssueTracker:
    """The tracker for the active provider, configured from ``cfg``."""
    if cfg.provider == "github":
        return GitHubTracker(cfg.github)
    return JiraTracker(cfg.jira)


def active_config(cfg: EffectiveConfig) -> TrackerConfig:
    """The active provider's connection settings."""
    return cfg.github if cfg.provider == "github" else cfg.jira


def require_configured(cfg: EffectiveConfig) -> None:
    """Raise :class:`TrackerNotConfigured` unless the active tracker can be
    reached for.

    Callers that gate a release on the tracker's answer must distinguish "the
    tracker says there are no open issues" from "we never asked it". Fetching
    with no tracker configured yields an empty list, which reads as the former
    and would let a guarded transition through on no evidence at all.
    """
    active = active_config(cfg)
    if not (active.enabled and active.base_url):
        raise TrackerNotConfigured(
            f"the active issue tracker ({cfg.provider}) is not enabled/configured"
        )


def fetch_issues(
    cfg: EffectiveConfig, query: str, *, repo: str = "", filter_kind: str = ""
) -> list[dict]:
    """Fetch the issues contained in a release from the active tracker."""
    return get_tracker(cfg).fetch_issues(query, repo=repo, filter_kind=filter_kind)


def fetch_issue(cfg: EffectiveConfig, key: str, *, repo: str = "") -> dict | None:
    """Fetch one issue in full from the active tracker, or None when it is gone."""
    return get_tracker(cfg).fetch_issue(key, repo=repo)


def set_membership(
    cfg: EffectiveConfig, key: str, *, mode: str, value: str, member: bool, repo: str = ""
) -> None:
    """Edit an issue so it matches (or stops matching) a release's criteria."""
    get_tracker(cfg).set_membership(
        key, mode=mode, value=value, member=member, repo=repo
    )


def verify_project(cfg: EffectiveConfig, repo: str) -> None:
    """Confirm ``repo`` exists on the active tracker. Raises
    :class:`TrackerProjectNotFound` or :class:`TrackerUnreachable` otherwise."""
    get_tracker(cfg).verify_project(repo)
