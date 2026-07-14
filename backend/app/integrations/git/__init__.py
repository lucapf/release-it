"""Git-hosting integrations — pluggable, selected per repository link.

Unlike the issue tracker (exactly one active provider), both git connections
may be configured at once: each linked repository names its own provider, so a
product's repos can span GitHub and a self-hosted GitLab.

Each provider is implemented in its own module behind the common
:class:`GitProvider` interface (see ``base.py``):

  * GitHub — ``github.GitHubGitProvider`` (GitHub REST API)
  * GitLab — ``gitlab.GitLabGitProvider`` (GitLab REST API v4)

There are no in-process stubs: a provider calls its real backing service, and
an unconfigured one raises :class:`GitNotConfigured` rather than answering
with an empty change-set.
"""
from __future__ import annotations

from app.integrations.git.base import (
    MAX_COMMITS,
    MAX_MESSAGE_CHARS,
    MAX_PATCH_CHARS,
    GitCommit,
    GitCompare,
    GitError,
    GitFileDiff,
    GitFileNotFound,
    GitNotConfigured,
    GitProvider,
    GitRefNotFound,
    GitRepoNotFound,
    GitUnreachable,
)
from app.integrations.git.github import GitHubGitProvider
from app.integrations.git.gitlab import GitLabGitProvider
from app.services.appconfig import EffectiveConfig, GitProviderConfig

__all__ = [
    "GitProvider", "GitHubGitProvider", "GitLabGitProvider",
    "GitCommit", "GitCompare", "GitFileDiff",
    "GitError", "GitNotConfigured", "GitUnreachable",
    "GitRepoNotFound", "GitRefNotFound", "GitFileNotFound",
    "MAX_COMMITS", "MAX_MESSAGE_CHARS", "MAX_PATCH_CHARS",
    "provider_config", "get_git_provider", "require_git_configured",
    "repo_web_url",
]


def provider_config(cfg: EffectiveConfig, provider: str) -> GitProviderConfig:
    """The connection settings for ``provider`` ("github" | "gitlab")."""
    if provider == "gitlab":
        return cfg.git_gitlab
    return cfg.git_github


def repo_web_url(cfg: EffectiveConfig, provider: str, repo: str, override: str = "") -> str:
    """The repository's page on its hosting.

    The stored per-link ``override`` wins when set; otherwise the URL is
    derived from the provider connection (github.com/owner/repo, or the GitLab
    instance root + project path), so the link field is optional for the
    common case. Empty only when nothing can be derived (no GitLab URL yet).
    """
    if override:
        return override
    if provider == "gitlab":
        base = cfg.git_gitlab.base_url.rstrip("/")
        return f"{base}/{repo}" if base else ""
    from app.integrations.git.github import web_base

    return f"{web_base(cfg.git_github.base_url or 'https://api.github.com')}/{repo}"


def require_git_configured(cfg: EffectiveConfig, provider: str) -> None:
    """Raise :class:`GitNotConfigured` unless ``provider`` can be asked.

    Callers reporting on a release's code must distinguish "the hosting says
    nothing changed" from "we never asked it": with no connection configured,
    an empty answer would read as a clean bill of health.
    """
    active = provider_config(cfg, provider)
    if not (active.enabled and active.base_url):
        raise GitNotConfigured(
            f"the {provider} git connection is not enabled/configured"
        )


def get_git_provider(cfg: EffectiveConfig, provider: str) -> GitProvider:
    """The provider adapter for a repository link, configured from ``cfg``.
    Raises :class:`GitNotConfigured` when that connection is not set up."""
    require_git_configured(cfg, provider)
    if provider == "gitlab":
        return GitLabGitProvider(cfg.git_gitlab)
    return GitHubGitProvider(cfg.git_github)
