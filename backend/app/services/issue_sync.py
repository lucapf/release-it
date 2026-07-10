"""Scheduled issue sync — periodically refresh every running release's issues
from the active tracker.

The interval is runtime-configurable (``sync_interval_minutes`` on the
configuration page, default 10; 0 disables the scheduler). Each cycle mirrors
what an operator's "Sync now" does, per release: the saved sync filter is
applied when one exists, otherwise the provider default (GitHub: milestone =
release version; Jira: ``fixVersion = "<version>"``). The issue cache is only
replaced — and an audit entry recorded — when the fetched set actually differs,
so a quiet tracker doesn't flood the release history every cycle.
"""
from __future__ import annotations

import logging

import psycopg

from app.integrations import trackers
from app.repositories import jira_issues as jira_repo
from app.repositories import products as products_repo
from app.repositories import releases as releases_repo
from app.repositories import sync_filters as filters_repo
from app.services import appconfig, audit
from app.services.state_machine import StateMachine

log = logging.getLogger("releaseit.issue_sync")

# Operator recorded on audit entries written by the scheduler.
SCHEDULER_OPERATOR = "scheduler"


def _query_for(cfg: appconfig.EffectiveConfig, rel: dict, saved: dict | None) -> tuple[str, str]:
    """Resolve a release's tracker filter to ``(query, filter_kind)``, honouring
    the saved sync filter first — the same semantics as the manual sync API."""
    mode = (saved or {}).get("filter_mode", "")
    value = ((saved or {}).get("filter_value", "") or "").strip()

    if cfg.provider == "github":
        if mode == "label" and value:
            return value, "label"
        if mode == "milestone" and value:
            return value, "milestone"
        return rel["version"], "milestone"

    if mode == "jql" and value:
        return value, "jql"
    if mode == "label" and value:
        return f'labels = "{value}"', "jql"
    return f'fixVersion = "{rel["version"]}"', "jql"


def _issue_set(issues: list[dict], key: str, typ: str, summary: str, status: str) -> set[tuple]:
    return {(i[key], i[typ], i[summary], i[status], i.get("url", "")) for i in issues}


def sync_release(conn: psycopg.Connection, cfg: appconfig.EffectiveConfig, rel: dict) -> bool:
    """Sync one release's issues; returns True when the cache changed."""
    product = products_repo.get(conn, rel["product_id"]) or {}
    repo_slug = product.get("tracker_repo", "") or ""
    if cfg.provider == "github" and not repo_slug:
        return False  # no repository bound to this product yet — nothing to sync

    query, filter_kind = _query_for(cfg, rel, filters_repo.get(conn, rel["id"]))
    issues = trackers.fetch_issues(cfg, query, repo=repo_slug, filter_kind=filter_kind)

    cached = jira_repo.list_by_release(conn, rel["id"])
    if _issue_set(issues, "key", "type", "summary", "status") == _issue_set(
        cached, "issue_key", "issue_type", "summary", "status"
    ):
        return False  # unchanged — leave the cache and history alone

    jira_repo.replace_for_release(conn, rel["id"], issues)
    audit.record(conn, entity_type="release", entity_id=rel["id"],
                 action="jira_sync", operator=SCHEDULER_OPERATOR, new_value=query)
    return True


def sync_all(conn: psycopg.Connection, sm: StateMachine) -> int:
    """Sync every running (non-final) release. Per-release failures are logged
    and skipped so one broken filter can't stall the whole cycle. Returns how
    many releases had their issue cache updated."""
    cfg = appconfig.effective(conn)
    active = cfg.github if cfg.provider == "github" else cfg.jira
    if not (active.enabled and active.base_url):
        return 0  # tracker not configured — don't wipe caches with empty fetches

    final_states = {s.name for s in sm.states() if s.is_final}
    changed = 0
    for rel in releases_repo.list_all(conn):
        if rel["state"] in final_states:
            continue
        try:
            with conn.transaction():
                if sync_release(conn, cfg, rel):
                    changed += 1
        except Exception:
            log.exception("scheduled sync failed for release %s (v%s)",
                          rel["id"], rel["version"])
    return changed
