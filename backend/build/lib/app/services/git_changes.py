"""Release change detection — what code a release ships, computed live.

A product's deployment repo (the Helm umbrella chart, app-of-apps) is tagged
with the product release version, and its Chart.yaml dependencies list every
service name + version. The change-set of a release is therefore:

  1. diff the umbrella Chart.yaml between the previous release's tag and this
     release's tag → which services changed, and their old→new versions;
  2. for each changed service, diff its own repository between the two version
     tags (the link's tag_pattern renders a version into a tag name).

Commits are mapped to tickets by the references they carry — ticket IDs in the
commit message (``#123``, ``PROJ-123``) and branch-name conventions parsed from
merge-commit subjects. A commit with no reference is reported as unmapped,
never guessed.

Nothing here is cached or stored: like the issue side of the app, the answer
is computed against the hosting at the moment it is asked, and "we could not
check" (GitNotConfigured/GitUnreachable, or a per-component ``error`` status)
is always distinct from "there are no changes".
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import psycopg
import yaml

from app.integrations import git
from app.integrations.git import (
    GitCompare,
    GitError,
    GitFileNotFound,
    GitNotConfigured,
    GitRefNotFound,
    GitUnreachable,
)
from app.repositories import git_repos as git_repos_repo
from app.repositories import releases as releases_repo
from app.services.appconfig import EffectiveConfig

log = logging.getLogger("releaseit.git_changes")


class ChangesUnavailable(Exception):
    """The change-set cannot be computed at all (no umbrella repo linked).
    Per-component failures do not raise — they ride in the result."""


# --- Ticket extraction --------------------------------------------------------
# GitHub-style issue reference: "#123" (not part of a word or a sha fragment).
_GITHUB_TICKET_RE = re.compile(r"(?<![\w#])#(\d+)\b")
# Jira-style key: "PROJ-123".
_JIRA_TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
# Branch name inside a merge-commit subject: Merge branch 'feature/123-x' ...
_MERGE_BRANCH_RE = re.compile(r"[Mm]erge (?:branch|remote-tracking branch) '([^']+)'")
# Ticket at the start of a branch path segment: feature/123-add-login,
# 456-fix, feature/PROJ-9-cleanup.
_BRANCH_TICKET_RE = re.compile(r"(?:^|/)(?:(\d+)|([A-Z][A-Z0-9]+-\d+))(?=[-_/]|$)")


def extract_tickets(subject: str, message: str) -> list[str]:
    """The ticket references a commit carries, normalized ("#123", "PROJ-123").
    Empty means unmapped — the caller reports that, it never guesses."""
    text = f"{subject}\n{message}"
    tickets: list[str] = []

    def add(ref: str) -> None:
        if ref not in tickets:
            tickets.append(ref)

    for num in _GITHUB_TICKET_RE.findall(text):
        add(f"#{num}")
    for key in _JIRA_TICKET_RE.findall(text):
        add(key)
    for branch in _MERGE_BRANCH_RE.findall(text):
        m = _BRANCH_TICKET_RE.search(branch)
        if m:
            add(f"#{m.group(1)}" if m.group(1) else m.group(2))
    return tickets


def render_tag(pattern: str, version: str) -> str:
    """A version rendered into the repo's tag name, e.g. 'v{version}' → 'v1.2.0'.
    An unknown placeholder falls back to the default pattern rather than
    producing a tag that can never exist."""
    try:
        return (pattern or "v{version}").format(version=version)
    except (KeyError, IndexError, ValueError):
        return f"v{version}"


def parse_chart_dependencies(chart_yaml: str) -> dict[str, str]:
    """Chart.yaml dependencies as {name: version}. Raises ValueError with an
    operator-actionable message on malformed YAML."""
    try:
        data = yaml.safe_load(chart_yaml)
    except yaml.YAMLError as exc:
        raise ValueError(f"Chart.yaml is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Chart.yaml does not contain a mapping")
    deps = data.get("dependencies") or []
    if not isinstance(deps, list):
        raise ValueError("Chart.yaml 'dependencies' is not a list")
    out: dict[str, str] = {}
    for d in deps:
        if isinstance(d, dict) and d.get("name"):
            out[str(d["name"])] = str(d.get("version", ""))
    return out


# --- Result shapes -------------------------------------------------------------
@dataclass
class CommitTickets:
    sha: str
    short_sha: str
    subject: str
    author: str
    url: str
    tickets: list[str] = field(default_factory=list)


@dataclass
class ComponentChange:
    name: str
    repo_id: int | None = None
    repo: str = ""
    provider: str = ""
    web_url: str = ""
    old_version: str | None = None
    new_version: str | None = None
    status: str = "unchanged"  # changed | added | removed | unchanged | error
    error: str = ""
    compare: GitCompare | None = None  # raw compare, service-layer only
    compare_url: str = ""
    commit_count: int = 0
    commits_truncated: bool = False
    commits: list[CommitTickets] = field(default_factory=list)
    mapped_count: int = 0
    unmapped_count: int = 0


@dataclass
class ReleaseChangeSet:
    release_id: int
    version: str
    previous_release_id: int | None
    previous_version: str | None
    umbrella_repo: str
    umbrella_provider: str
    old_tag: str | None
    new_tag: str | None
    baseline_missing: str = ""
    components: list[ComponentChange] = field(default_factory=list)
    unmatched_dependencies: list[dict] = field(default_factory=list)
    library_repos: list[dict] = field(default_factory=list)


# --- Core ----------------------------------------------------------------------
def compute_release_changes(
    conn: psycopg.Connection, cfg: EffectiveConfig, rel: dict
) -> ReleaseChangeSet:
    """The change-set of a release, read live from the git hosting.

    Raises :class:`ChangesUnavailable` when no deployment repo is linked, and
    lets :class:`GitNotConfigured`/:class:`GitUnreachable` from the *umbrella*
    repo propagate — with no umbrella answer there is no change-set at all.
    Per-component failures are contained in their entry (``status='error'``).
    """
    deployment = git_repos_repo.deployment_for(conn, rel["product_id"])
    if deployment is None:
        raise ChangesUnavailable(
            "no deployment (umbrella chart) repository is linked to this product"
        )
    provider = git.get_git_provider(cfg, deployment["provider"])

    prev = releases_repo.previous_release(conn, rel["id"])
    new_tag = render_tag(deployment["tag_pattern"], rel["version"])
    result = ReleaseChangeSet(
        release_id=rel["id"],
        version=rel["version"],
        previous_release_id=prev["id"] if prev else None,
        previous_version=prev["version"] if prev else None,
        umbrella_repo=deployment["repo"],
        umbrella_provider=deployment["provider"],
        old_tag=None,
        new_tag=new_tag,
        library_repos=[
            r for r in git_repos_repo.list_for_product(conn, rel["product_id"])
            if r["role"] == "library"
        ],
    )

    # This release's Chart.yaml. Without it there is nothing to report on.
    try:
        provider.resolve_tag(deployment["repo"], new_tag)
        new_deps = parse_chart_dependencies(
            provider.read_file_at_ref(deployment["repo"], deployment["chart_path"], new_tag)
        )
    except GitRefNotFound:
        result.new_tag = None
        result.baseline_missing = (
            f'tag "{new_tag}" does not exist yet in {deployment["repo"]} — '
            "the release has not been tagged"
        )
        return result
    except (GitFileNotFound, ValueError) as exc:
        result.baseline_missing = f"cannot read the umbrella chart at {new_tag}: {exc}"
        return result

    # The baseline Chart.yaml. Missing baseline → report current versions only.
    old_deps: dict[str, str] | None = None
    if prev is None:
        result.baseline_missing = (
            "this is the product's first release — there is no previous version to diff against"
        )
    else:
        old_tag = render_tag(deployment["tag_pattern"], prev["version"])
        try:
            provider.resolve_tag(deployment["repo"], old_tag)
            old_deps = parse_chart_dependencies(
                provider.read_file_at_ref(
                    deployment["repo"], deployment["chart_path"], old_tag
                )
            )
            result.old_tag = old_tag
        except GitRefNotFound:
            result.baseline_missing = (
                f'the previous release\'s tag "{old_tag}" does not exist in '
                f"{deployment['repo']}"
            )
        except (GitFileNotFound, ValueError) as exc:
            result.baseline_missing = (
                f"cannot read the umbrella chart at {old_tag}: {exc}"
            )

    components_by_name = git_repos_repo.components_for(conn, rel["product_id"])
    names = sorted(set(new_deps) | set(old_deps or {}))
    for name in names:
        old_v = (old_deps or {}).get(name)
        new_v = new_deps.get(name)
        if old_deps is None:
            # No baseline to compare against: report current versions only.
            status = "unchanged"
        elif old_v is None:
            status = "added"
        elif new_v is None:
            status = "removed"
        elif old_v != new_v:
            status = "changed"
        else:
            status = "unchanged"

        link = components_by_name.get(name)
        if link is None:
            result.unmatched_dependencies.append(
                {"name": name, "old_version": old_v, "new_version": new_v}
            )
            continue

        change = ComponentChange(
            name=name,
            repo_id=link["id"],
            repo=link["repo"],
            provider=link["provider"],
            web_url=link["web_url"],
            old_version=old_v,
            new_version=new_v,
            status=status,
        )
        if status == "changed":
            _diff_component(cfg, link, change)
        result.components.append(change)

    return result


def _diff_component(cfg: EffectiveConfig, link: dict, change: ComponentChange) -> None:
    """Fill a changed component's commits/diff from its own repository. Any
    failure lands in ``status='error'`` + ``error`` — one broken component must
    not sink the whole report."""
    old_tag = render_tag(link["tag_pattern"], change.old_version or "")
    new_tag = render_tag(link["tag_pattern"], change.new_version or "")
    try:
        provider = git.get_git_provider(cfg, link["provider"])
        compare = provider.compare(link["repo"], old_tag, new_tag)
    except (GitNotConfigured, GitUnreachable, GitRefNotFound, GitError) as exc:
        change.status = "error"
        change.error = f"could not diff {link['repo']} {old_tag}..{new_tag}: {exc}"
        return

    change.compare = compare
    change.compare_url = compare.web_url
    change.commit_count = compare.total_commits
    change.commits_truncated = compare.commits_truncated
    for c in compare.commits:
        tickets = extract_tickets(c.subject, c.message)
        change.commits.append(CommitTickets(
            sha=c.sha,
            short_sha=c.short_sha,
            subject=c.subject,
            author=c.author,
            url=c.url,
            tickets=tickets,
        ))
        if tickets:
            change.mapped_count += 1
        else:
            change.unmapped_count += 1


def changes_view(cs: ReleaseChangeSet, *, with_commits: bool = True) -> dict:
    """The change-set as the API/assistant response shape: everything except
    raw file diffs, which never leave the service layer."""
    return {
        "release_id": cs.release_id,
        "version": cs.version,
        "previous_release_id": cs.previous_release_id,
        "previous_version": cs.previous_version,
        "umbrella_repo": cs.umbrella_repo,
        "umbrella_provider": cs.umbrella_provider,
        "old_tag": cs.old_tag,
        "new_tag": cs.new_tag,
        "baseline_missing": cs.baseline_missing,
        "components": [
            {
                "name": c.name,
                "repo_id": c.repo_id,
                "repo": c.repo,
                "provider": c.provider,
                "web_url": c.web_url,
                "old_version": c.old_version,
                "new_version": c.new_version,
                "status": c.status,
                "error": c.error,
                "compare_url": c.compare_url,
                "commit_count": c.commit_count,
                "commits_truncated": c.commits_truncated,
                "commits": [
                    {
                        "sha": k.sha,
                        "short_sha": k.short_sha,
                        "subject": k.subject,
                        "author": k.author,
                        "url": k.url,
                        "tickets": k.tickets,
                    }
                    for k in (c.commits if with_commits else [])
                ],
                "mapped_count": c.mapped_count,
                "unmapped_count": c.unmapped_count,
            }
            for c in cs.components
        ],
        "unmatched_dependencies": cs.unmatched_dependencies,
        "library_repos": cs.library_repos,
    }
