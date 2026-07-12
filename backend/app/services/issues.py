"""A release's issues — always read live from the ticketing system.

The ticketing system owns which tickets exist, what state they are in, and
therefore which of them are still open. Release-It owns exactly one thing about
them: the *search criteria* that says which tickets belong to a release (e.g.
``label = v0.0.1``), chosen when the release is created and stored against it.

Everything that needs a release's issues — the issue list, the bug count, the
status page, the readiness gate, the assistant — resolves that criteria into a
tracker query here and asks the tracker. Nothing is cached in the database: the
``jira_issue`` table used to hold a copy behind a poll, which meant the answer a
caller got depended on when it asked rather than on what the tracker said.

Every call can therefore fail (the tracker is down, unconfigured, or the query is
malformed) and callers must let that fail rather than substituting an empty issue
list — an empty list reads as "nothing is open", which is the answer that lets a
release through a readiness gate.
"""
from __future__ import annotations

import psycopg

from app.integrations import trackers
from app.repositories import issue_filters as filters_repo
from app.repositories import products as products_repo
from app.services import appconfig

# The criteria an operator may choose, per tracker. A GitHub milestone has no
# Jira counterpart and JQL has no GitHub counterpart, so the valid set depends on
# the active provider; anything else is rejected rather than quietly falling back
# to the provider default (which would silently search for the wrong tickets).
MODES_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    "github": ("milestone", "label"),
    "jira": ("label", "jql"),
}


class IssueCriteriaError(ValueError):
    """The supplied search criteria cannot be applied to the active tracker."""


def validate_criteria(cfg: appconfig.EffectiveConfig, mode: str, value: str) -> tuple[str, str]:
    """Check a (mode, value) criteria against the active tracker, normalized.

    Raises :class:`IssueCriteriaError` when the mode is not one the active
    tracker supports, or the value is blank — a release's contents must be a
    definite question we can put to the tracker.
    """
    mode = (mode or "").strip().lower()
    value = (value or "").strip()
    allowed = MODES_BY_PROVIDER.get(cfg.provider, ())
    if mode not in allowed:
        raise IssueCriteriaError(
            f"'{mode or 'empty'}' is not a search criteria the active tracker "
            f"({cfg.provider}) supports — use one of: {', '.join(allowed)}"
        )
    if not value:
        raise IssueCriteriaError(f"Provide a value for the {mode} to search for")
    return mode, value


def get_criteria(conn: psycopg.Connection, release_id: int) -> dict | None:
    """The search criteria stored for a release, or None for a release created
    before criteria were recorded (those fall back to the provider default)."""
    return filters_repo.get(conn, release_id)


def save_criteria(
    conn: psycopg.Connection, release_id: int, mode: str, value: str
) -> dict:
    return filters_repo.upsert(conn, release_id, mode, value)


def copy_criteria(conn: psycopg.Connection, *, source_id: int, target_id: int) -> None:
    """An inherited release contains the same work as its parent, so it inherits
    the criteria that defines that work."""
    filters_repo.copy(conn, source_id, target_id)


def product_repo(conn: psycopg.Connection, release: dict) -> str:
    """The tracker project ('owner/repo') bound to this release's product."""
    product = products_repo.get(conn, release["product_id"]) or {}
    return (product.get("tracker_repo", "") or "").strip()


def _require_project(cfg: appconfig.EffectiveConfig, repo_slug: str) -> None:
    """GitHub cannot be queried without a repository — refuse rather than search
    nothing and report no issues."""
    if cfg.provider == "github" and not repo_slug:
        raise trackers.TrackerNotConfigured(
            "no GitHub repository is bound to this release's product — set it on "
            "the product's Issues tab (e.g. 'owner/repo')"
        )


def release_query(
    conn: psycopg.Connection, cfg: appconfig.EffectiveConfig, release: dict
) -> str:
    """The tracker query for a release's stored criteria (diagnostic: it tells an
    operator which tickets a count or a list was taken over)."""
    query, _ = _resolve(conn, cfg, release)
    return query


def _resolve(
    conn: psycopg.Connection, cfg: appconfig.EffectiveConfig, release: dict
) -> tuple[str, str]:
    saved = get_criteria(conn, release["id"]) or {}
    return trackers.release_query(
        cfg, release,
        mode=saved.get("filter_mode", "") or "",
        value=saved.get("filter_value", "") or "",
    )


def for_release(
    conn: psycopg.Connection, cfg: appconfig.EffectiveConfig, release: dict
) -> list[dict]:
    """The tickets this release contains, read from the tracker right now.

    Raises :class:`~app.integrations.trackers.TrackerNotConfigured` when there is
    no tracker to ask, and the underlying tracker/``httpx`` error when it cannot
    be reached. Callers must not turn either into an empty list.
    """
    trackers.require_configured(cfg)
    repo_slug = product_repo(conn, release)
    _require_project(cfg, repo_slug)
    query, filter_kind = _resolve(conn, cfg, release)
    return trackers.fetch_issues(cfg, query, repo=repo_slug, filter_kind=filter_kind)


def detail(
    conn: psycopg.Connection, cfg: appconfig.EffectiveConfig, release: dict, key: str
) -> dict:
    """One ticket in full — key, summary, description, status and the link to it in
    the ticketing system, for an operator who wants more than the list shows.

    Raises :class:`~app.integrations.trackers.IssueNotFound` when the tracker has
    no such ticket, so "there is no REL-9" never reads as an empty ticket.
    """
    trackers.require_configured(cfg)
    repo_slug = product_repo(conn, release)
    _require_project(cfg, repo_slug)
    issue = trackers.fetch_issue(cfg, key.strip(), repo=repo_slug)
    if issue is None:
        raise trackers.IssueNotFound(key)
    return issue


def membership_criteria(
    conn: psycopg.Connection, cfg: appconfig.EffectiveConfig, release: dict
) -> tuple[str, str]:
    """The release's criteria as the raw ``(mode, value)`` an edit has to satisfy.

    Deliberately *not* the resolved tracker query: a Jira label criteria resolves
    to the JQL ``labels = "v0.0.1"``, and you cannot add a JQL string to a ticket.
    Adding a ticket to a release means making it match the criteria, so what the
    edit needs is the criteria itself.
    """
    saved = get_criteria(conn, release["id"])
    if saved:
        return saved["filter_mode"], saved["filter_value"]
    if cfg.provider == "github":
        return "milestone", release["version"]  # the provider default
    raise IssueCriteriaError(
        "this release has no stored search criteria, so there is nothing a ticket "
        "could be edited to match. Give it one (e.g. label = v0.0.1) first."
    )


def set_membership(
    conn: psycopg.Connection,
    cfg: appconfig.EffectiveConfig,
    release: dict,
    key: str,
    *,
    member: bool,
) -> dict:
    """Add (``member=True``) or remove a ticket from a release, and report back
    what the tracker now says about it.

    A ticket is in a release because it *matches the release's criteria* — that is
    the only definition there is, since Release-It stores no membership of its own.
    So this edits the ticket in the ticketing system until it matches (a label
    criteria → add the label) or until it no longer does (→ remove the label). The
    change lands in the tracker, where everyone else can see it, rather than in a
    private list only Release-It would know about.

    The result is then read back from the tracker: the edit is only reported as
    successful if the release's own issue query now actually contains (or no longer
    contains) the ticket. An edit we *believe* worked is not the same as a release
    whose contents changed, and the operator is entitled to the latter.
    """
    key = (key or "").strip()
    if not key:
        raise IssueCriteriaError("Provide the key of the ticket, e.g. 'REL-1' or '#12'")

    trackers.require_configured(cfg)
    repo_slug = product_repo(conn, release)
    _require_project(cfg, repo_slug)
    mode, value = membership_criteria(conn, cfg, release)

    trackers.set_membership(
        cfg, key, mode=mode, value=value, member=member, repo=repo_slug
    )

    issues = for_release(conn, cfg, release)
    now_in = any(i["key"].strip().lower() == key.lower() for i in issues)
    if now_in != member:
        # The tracker accepted the edit but the release's query still disagrees —
        # the criteria selects on something the edit didn't change. Say so plainly
        # instead of reporting a success the issue list will contradict.
        raise IssueCriteriaError(
            f'{key} was edited, but the release still does {"not " if member else ""}'
            f'contain it: its criteria ({mode} = {value}) selects tickets on '
            "something that edit did not change."
        )
    return {"key": key, "member": member, "criteria": f"{mode} = {value}",
            "total": len(issues), "issues": issues}


def search(
    conn: psycopg.Connection,
    cfg: appconfig.EffectiveConfig,
    product_id: int,
    mode: str,
    value: str,
) -> tuple[str, list[dict]]:
    """Run a criteria against the tracker without a release, as ``(query,
    issues)``.

    This is what backs the preview an operator sees while creating a release:
    they choose the criteria, see the tickets it actually finds, and only then is
    the release created with it. A criteria that turns out to select the wrong
    work is far cheaper to correct here than after the release exists.
    """
    mode, value = validate_criteria(cfg, mode, value)
    trackers.require_configured(cfg)
    product = products_repo.get(conn, product_id)
    if product is None:
        raise IssueCriteriaError("Product not found")
    repo_slug = (product.get("tracker_repo", "") or "").strip()
    _require_project(cfg, repo_slug)
    # No release exists yet, so there is no version for the provider default to
    # fall back on — the criteria is validated above and always resolves.
    query, filter_kind = trackers.release_query(
        cfg, {"version": ""}, mode=mode, value=value
    )
    return query, trackers.fetch_issues(cfg, query, repo=repo_slug, filter_kind=filter_kind)
