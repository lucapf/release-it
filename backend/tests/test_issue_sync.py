"""Scheduled issue sync: filter resolution and the configured interval.

No database — the filter resolver is pure, and the interval parsing is
exercised by faking the app_config key/value store.
"""
from __future__ import annotations

from app.services import appconfig
from app.services.issue_sync import _query_for


def _cfg(provider: str) -> appconfig.EffectiveConfig:
    tracker = appconfig.TrackerConfig(enabled=True, base_url="http://t", token="")
    llm = appconfig.LLMConfig("claude", "", "", "", "")
    return appconfig.EffectiveConfig(provider=provider, jira=tracker, github=tracker, llm=llm)


REL = {"id": 1, "version": "1.2.0"}


def test_query_honours_saved_filter_github():
    cfg = _cfg("github")
    assert _query_for(cfg, REL, {"filter_mode": "label", "filter_value": "v1.2.0"}) == ("v1.2.0", "label")
    assert _query_for(cfg, REL, {"filter_mode": "milestone", "filter_value": "M1"}) == ("M1", "milestone")
    # No saved filter -> GitHub defaults to the release-version milestone.
    assert _query_for(cfg, REL, None) == ("1.2.0", "milestone")


def test_query_honours_saved_filter_jira():
    cfg = _cfg("jira")
    assert _query_for(cfg, REL, {"filter_mode": "jql", "filter_value": "project = REL"}) == ("project = REL", "jql")
    assert _query_for(cfg, REL, {"filter_mode": "label", "filter_value": "2025-Q3"}) == ('labels = "2025-Q3"', "jql")
    # No saved filter -> Jira defaults to fixVersion = <version>.
    assert _query_for(cfg, REL, None) == ('fixVersion = "1.2.0"', "jql")


def test_sync_interval_defaults_to_10_minutes(monkeypatch):
    monkeypatch.setattr(appconfig.repo, "get_all", lambda conn: {})
    assert appconfig.effective(None).sync_interval_minutes == 10


def test_sync_interval_is_runtime_configurable(monkeypatch):
    monkeypatch.setattr(
        appconfig.repo, "get_all", lambda conn: {appconfig.SYNC_INTERVAL_MINUTES: "25"}
    )
    assert appconfig.effective(None).sync_interval_minutes == 25
    # Garbage in the store falls back to the default rather than crashing.
    monkeypatch.setattr(
        appconfig.repo, "get_all", lambda conn: {appconfig.SYNC_INTERVAL_MINUTES: "soon"}
    )
    assert appconfig.effective(None).sync_interval_minutes == 10
