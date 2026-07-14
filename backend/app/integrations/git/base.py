"""Common git-hosting interface.

A git provider reads a product's source repositories through the hosting
service's API: it resolves version tags, reads a file at a ref (the umbrella
Chart.yaml) and compares two refs into commits + per-file diffs. Reads are
always live — nothing is cloned or cached, so "we could not check" and "there
are no changes" can never look the same.

Concrete providers live in their own modules (``github.py``, ``gitlab.py``)
and implement :class:`GitProvider`. There are no in-process stubs: a provider
talks to its real backing service.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

# Bounds applied by every adapter, so no caller ever receives an unbounded
# payload. Truncation is always flagged, never silent.
MAX_PATCH_CHARS = 20_000   # per-file unified diff
MAX_COMMITS = 500          # commits collected per compare
MAX_MESSAGE_CHARS = 2_000  # full commit message


@dataclass
class GitCommit:
    sha: str
    short_sha: str
    subject: str        # first line of the message
    message: str        # full message, capped at MAX_MESSAGE_CHARS
    author: str = ""
    authored_at: str = ""  # ISO string as the provider reports it
    url: str = ""          # the commit's page in the hosting web UI


@dataclass
class GitFileDiff:
    path: str
    status: str = "modified"  # added | modified | removed | renamed
    additions: int = 0
    deletions: int = 0
    patch: str = ""           # unified diff; "" for binary or withheld content
    truncated: bool = False   # patch cut at MAX_PATCH_CHARS or withheld


@dataclass
class GitCompare:
    base_ref: str
    head_ref: str
    commits: list[GitCommit] = field(default_factory=list)
    files: list[GitFileDiff] = field(default_factory=list)
    total_commits: int = 0        # the provider's count; may exceed len(commits)
    commits_truncated: bool = False
    files_truncated: bool = False
    web_url: str = ""             # the hosting's own compare page


# --- Errors ------------------------------------------------------------------
class GitError(Exception):
    """Base class for git-hosting connectivity/validation failures."""


class GitNotConfigured(GitError):
    """The repo's provider connection is not enabled/configured.

    Raised rather than answering with an empty change-set: callers that report
    on a release's code must distinguish "the hosting says nothing changed"
    from "we never asked it".
    """


class GitUnreachable(GitError):
    """The hosting could not be reached (bad URL/credentials, network error)."""


class GitRepoNotFound(GitError):
    """The named repository does not exist on the hosting (or is not visible
    with the configured credentials)."""


class GitRefNotFound(GitError):
    """The tag/ref does not exist in the repository."""


class GitFileNotFound(GitError):
    """The file does not exist at that ref (e.g. no Chart.yaml)."""


class GitProvider(Protocol):
    """Reads a repository on a git hosting service. ``repo`` is the provider's
    repository identifier: GitHub ``"owner/repo"``, GitLab ``"group/project"``.
    """

    def verify_repo(self, repo: str) -> None:
        """Confirm ``repo`` exists on the hosting. Returns normally when it
        does; raises :class:`GitRepoNotFound` when it does not, or
        :class:`GitUnreachable` when the hosting cannot be reached."""
        ...

    def resolve_tag(self, repo: str, tag: str) -> str:
        """The commit sha a tag points at (annotated tags are peeled).
        Raises :class:`GitRefNotFound` when the tag does not exist."""
        ...

    def read_file_at_ref(self, repo: str, path: str, ref: str) -> str:
        """The text content of ``path`` at ``ref``. Raises
        :class:`GitFileNotFound` when the file is absent at that ref."""
        ...

    def compare(self, repo: str, base_ref: str, head_ref: str) -> GitCompare:
        """Commits and per-file diffs between two refs (``base..head``),
        bounded and truncation-flagged per the module constants."""
        ...


def cap_patch(patch: str) -> tuple[str, bool]:
    """``patch`` capped at MAX_PATCH_CHARS, with whether it was cut."""
    if len(patch) > MAX_PATCH_CHARS:
        return patch[:MAX_PATCH_CHARS], True
    return patch, False


def cap_message(message: str) -> str:
    return message[:MAX_MESSAGE_CHARS]
