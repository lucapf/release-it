"""Linking a git repository to a product.

Same stance as the tracker binding: a link nobody checked must not look like
one that passed. A repository can only be linked once the provider connection
that has to answer for it is configured, and "the hosting could not be asked"
is never reported as "the repository does not exist".

No database and no network: the config and the provider are faked.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1 import product as product_api
from app.integrations import git
from app.integrations.git import GitRepoNotFound, GitUnreachable
from app.services import appconfig


def _cfg(*, github_enabled=True, gitlab_enabled=False):
    off = appconfig.TrackerConfig(enabled=False, base_url="", token="")
    return appconfig.EffectiveConfig(
        provider="jira", jira=off, github=off,
        llm=appconfig.LLMConfig("claude", "", "", "", ""),
        git_github=appconfig.GitProviderConfig(
            enabled=github_enabled, base_url="https://api.github.com", token="t"
        ),
        git_gitlab=appconfig.GitProviderConfig(
            enabled=gitlab_enabled, base_url="https://gitlab.example.com", token="t"
        ),
    )


@pytest.fixture
def provider(monkeypatch):
    class Fake:
        def __init__(self):
            self.asked: list[str] = []
            self.raises: Exception | None = None

        def verify_repo(self, repo):
            self.asked.append(repo)
            if self.raises:
                raise self.raises

    fake = Fake()
    # get_git_provider still enforces its own not-configured check; only the
    # adapter construction is bypassed.
    monkeypatch.setattr(git, "GitHubGitProvider", lambda cfg: fake)
    monkeypatch.setattr(git, "GitLabGitProvider", lambda cfg: fake)
    return fake


def _verify(monkeypatch, cfg, provider_name, repo):
    monkeypatch.setattr(product_api.appconfig, "effective", lambda conn: cfg)
    product_api._verify_git_repo(None, provider_name, repo)


def test_existing_repository_is_accepted(monkeypatch, provider):
    _verify(monkeypatch, _cfg(), "github", "acme/app")
    assert provider.asked == ["acme/app"]


def test_unknown_repository_is_refused(monkeypatch, provider):
    provider.raises = GitRepoNotFound("acme/nope")
    with pytest.raises(HTTPException) as exc:
        _verify(monkeypatch, _cfg(), "github", "acme/nope")
    assert exc.value.status_code == 400
    assert "acme/nope" in exc.value.detail


def test_unreachable_hosting_is_not_mistaken_for_a_bad_repository(monkeypatch, provider):
    provider.raises = GitUnreachable("connection refused")
    with pytest.raises(HTTPException) as exc:
        _verify(monkeypatch, _cfg(), "github", "acme/app")
    assert exc.value.status_code == 502


def test_link_is_refused_when_the_connection_is_not_configured(monkeypatch, provider):
    with pytest.raises(HTTPException) as exc:
        _verify(monkeypatch, _cfg(github_enabled=False), "github", "acme/app")
    assert exc.value.status_code == 400
    assert "not enabled" in exc.value.detail
    assert provider.asked == []


def test_each_link_uses_its_own_provider_connection(monkeypatch, provider):
    """GitLab being configured does not vouch for a GitHub repository."""
    with pytest.raises(HTTPException):
        _verify(monkeypatch, _cfg(github_enabled=False, gitlab_enabled=True),
                "github", "acme/app")
    _verify(monkeypatch, _cfg(github_enabled=False, gitlab_enabled=True),
            "gitlab", "group/project")
    assert provider.asked == ["group/project"]


def test_web_url_is_derived_when_not_overridden():
    """The Web URL is optional: left empty, the repository's page is derived
    from the provider connection, so standalone/CLI products need no web
    configuration at all. A stored override always wins."""
    cfg = _cfg()
    assert git.repo_web_url(cfg, "github", "acme/app") == "https://github.com/acme/app"
    assert git.repo_web_url(cfg, "gitlab", "g/p") == "https://gitlab.example.com/g/p"
    assert git.repo_web_url(cfg, "github", "acme/app", "https://else.where") == "https://else.where"


def test_web_url_derivation_handles_enterprise_and_unconfigured_hosts():
    cfg = _cfg()
    cfg.git_github.base_url = "https://github.corp.example/api/v3"
    assert git.repo_web_url(cfg, "github", "acme/app") == "https://github.corp.example/acme/app"
    cfg.git_gitlab.base_url = ""
    # Nothing to derive from: no link rather than a made-up one.
    assert git.repo_web_url(cfg, "gitlab", "g/p") == ""


def test_component_link_requires_a_component_name():
    with pytest.raises(HTTPException) as exc:
        product_api._clean_link_fields("component", "   ")
    assert exc.value.status_code == 422
    assert product_api._clean_link_fields("library", "") == ""
    assert product_api._clean_link_fields("component", " moda ") == "moda"
