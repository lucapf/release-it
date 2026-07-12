"""Binding a product to an issue-tracker project.

A product's ``tracker_repo`` is the promise that its releases can be resolved to
real tickets. The promise is only worth something if it was checked against the
tracker that will have to keep it — so the binding is verified at the moment it
is saved, and a value that could not be verified is refused rather than stored.

The gap this covers: verification used to be skipped whenever the active tracker
was not enabled, which silently accepted *any* repository on a fresh install.

No database and no network: the config and the tracker are faked.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1 import product as product_api
from app.integrations import trackers
from app.integrations.trackers import TrackerProjectNotFound, TrackerUnreachable
from app.services import appconfig


def _cfg(provider: str, *, enabled: bool = True, base_url: str = "https://api.github.com"):
    tracker = appconfig.TrackerConfig(enabled=enabled, base_url=base_url, token="t")
    off = appconfig.TrackerConfig(enabled=False, base_url="", token="")
    llm = appconfig.LLMConfig("claude", "", "", "", "")
    return appconfig.EffectiveConfig(
        provider=provider,
        github=tracker if provider == "github" else off,
        jira=tracker if provider == "jira" else off,
        llm=llm,
    )


@pytest.fixture
def tracker(monkeypatch):
    """Stand in for the tracker: records what it was asked, answers as told."""

    class Fake:
        def __init__(self):
            self.asked: list[str] = []
            self.raises: Exception | None = None

        def verify_project(self, cfg, repo):
            self.asked.append(repo)
            if self.raises:
                raise self.raises

    fake = Fake()
    monkeypatch.setattr(trackers, "verify_project", fake.verify_project)
    monkeypatch.setattr(product_api.trackers, "verify_project", fake.verify_project)
    return fake


def _verify(monkeypatch, cfg, repo):
    monkeypatch.setattr(product_api.appconfig, "effective", lambda conn: cfg)
    product_api._verify_tracker_project(None, repo)


def test_existing_repository_is_accepted(monkeypatch, tracker):
    _verify(monkeypatch, _cfg("github"), "acme/app")
    assert tracker.asked == ["acme/app"]


def test_unknown_repository_is_refused(monkeypatch, tracker):
    tracker.raises = TrackerProjectNotFound("acme/nope")
    with pytest.raises(HTTPException) as exc:
        _verify(monkeypatch, _cfg("github"), "acme/nope")
    assert exc.value.status_code == 400
    assert "acme/nope" in exc.value.detail


def test_unreachable_tracker_is_not_mistaken_for_a_bad_repository(monkeypatch, tracker):
    """502, not 400: we did not learn that the repo is missing, only that we
    could not ask. Telling the operator their repo does not exist would be a lie."""
    tracker.raises = TrackerUnreachable("connection refused")
    with pytest.raises(HTTPException) as exc:
        _verify(monkeypatch, _cfg("github"), "acme/app")
    assert exc.value.status_code == 502


def test_repository_is_refused_when_no_tracker_is_enabled(monkeypatch, tracker):
    """The bug: with no tracker enabled there is nothing to verify against, and
    the save used to go through unchecked — so a product could be bound to a
    GitHub repository that does not exist. Refuse instead, and never ask."""
    with pytest.raises(HTTPException) as exc:
        _verify(monkeypatch, _cfg("github", enabled=False), "acme/does-not-exist")
    assert exc.value.status_code == 400
    assert "no issue tracker is enabled" in exc.value.detail
    assert "Jira" not in exc.value.detail  # the provider is just the default here
    assert tracker.asked == []


def test_repository_is_refused_when_credentials_exist_but_the_tracker_is_off(
    monkeypatch, tracker
):
    """The state the bug was actually hit in: GitHub credentials had been filled
    in (base_url + token) but the GitHub tracker was never switched on, so the
    active provider was still the disabled Jira default. Nothing was enabled, so
    nothing was checked, and a non-existent repository was accepted."""
    cfg = appconfig.EffectiveConfig(
        provider="jira",
        jira=appconfig.TrackerConfig(enabled=False, base_url="", token=""),
        github=appconfig.TrackerConfig(
            enabled=False, base_url="https://api.github.com", token="ghp_x"
        ),
        llm=appconfig.LLMConfig("claude", "", "", "", ""),
    )
    with pytest.raises(HTTPException) as exc:
        _verify(monkeypatch, cfg, "lucapf/rl_for_dummy")
    assert exc.value.status_code == 400
    assert tracker.asked == []


def test_repository_is_refused_when_the_enabled_tracker_has_no_url(monkeypatch, tracker):
    with pytest.raises(HTTPException) as exc:
        _verify(monkeypatch, _cfg("github", base_url=""), "acme/does-not-exist")
    assert exc.value.status_code == 400
    assert tracker.asked == []


def test_empty_binding_is_always_allowed(monkeypatch, tracker):
    """Clearing the binding asks the tracker nothing, so it stays possible even
    with no tracker configured — otherwise an unconfigured install could not undo
    a bad binding."""
    for value in ("", "   ", None):
        _verify(monkeypatch, _cfg("github", enabled=False), value)
    assert tracker.asked == []
