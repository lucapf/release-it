"""Effective runtime configuration: DB (app_config) overrides env defaults.

The configuration page persists values into the ``app_config`` table; anything
not set there falls back to the env-var defaults in ``app.core.config``. This
module is the single source of truth integrations read from.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import psycopg

from app.core.config import settings
from app.repositories import config as repo

# Keys persisted in app_config. Booleans are stored as "true"/"false".
TRACKER_PROVIDER = "tracker_provider"
JIRA_ENABLED = "jira_enabled"
JIRA_BASE_URL = "jira_base_url"
JIRA_TOKEN = "jira_token"
GITHUB_ENABLED = "github_enabled"
GITHUB_BASE_URL = "github_base_url"
GITHUB_TOKEN = "github_token"
# NOTE: the GitHub repository is configured per-product (Product.tracker_repo),
# not as a global app_config key.

LLM_PROVIDER = "llm_provider"
CLAUDE_API_KEY = "claude_api_key"
CLAUDE_MODEL = "claude_model"
OLLAMA_BASE_URL = "ollama_base_url"
OLLAMA_MODEL = "ollama_model"

# JSON map {"<state>|<transition>": ["Role", ...]} overriding the per-transition
# roles seeded from states.yaml. Lets an admin redefine who may transition.
TRANSITION_ROLES = "transition_roles"

SECRET_KEYS = {JIRA_TOKEN, GITHUB_TOKEN, CLAUDE_API_KEY}


def trans_key(state: str, transition: str) -> str:
    return f"{state}|{transition}"


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class TrackerConfig:
    enabled: bool
    base_url: str
    token: str


@dataclass
class LLMConfig:
    provider: str  # "claude" | "ollama"
    claude_api_key: str
    claude_model: str
    ollama_base_url: str
    ollama_model: str


@dataclass
class EffectiveConfig:
    provider: str
    jira: TrackerConfig
    github: TrackerConfig
    llm: LLMConfig


def effective(conn: psycopg.Connection) -> EffectiveConfig:
    db = repo.get_all(conn)

    def s(key: str, default: str) -> str:
        return db[key] if key in db and db[key] != "" else default

    def b(key: str, default: bool) -> bool:
        return _as_bool(db[key]) if key in db and db[key] != "" else default

    provider = s(TRACKER_PROVIDER, settings.tracker_provider).lower()
    if provider not in {"jira", "github"}:
        provider = "jira"

    return EffectiveConfig(
        provider=provider,
        jira=TrackerConfig(
            enabled=b(JIRA_ENABLED, settings.jira_enabled),
            base_url=s(JIRA_BASE_URL, settings.jira_base_url),
            token=s(JIRA_TOKEN, settings.jira_token),
        ),
        github=TrackerConfig(
            enabled=b(GITHUB_ENABLED, settings.github_enabled),
            base_url=s(GITHUB_BASE_URL, settings.github_base_url),
            token=s(GITHUB_TOKEN, settings.github_token),
        ),
        llm=LLMConfig(
            provider=s(LLM_PROVIDER, settings.llm_provider).lower(),
            claude_api_key=s(CLAUDE_API_KEY, settings.claude_api_key),
            claude_model=s(CLAUDE_MODEL, settings.claude_model),
            ollama_base_url=s(OLLAMA_BASE_URL, settings.ollama_base_url),
            ollama_model=s(OLLAMA_MODEL, settings.ollama_model),
        ),
    )


# --- Transition role overrides ---------------------------------------------
def transition_role_overrides(conn: psycopg.Connection) -> dict[str, list[str]]:
    """Admin-defined per-transition role overrides, keyed by '<state>|<name>'."""
    raw = repo.get_all(conn).get(TRANSITION_ROLES, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: list(v) for k, v in data.items() if isinstance(v, list)}


def set_transition_role_overrides(
    conn: psycopg.Connection, overrides: dict[str, list[str]]
) -> None:
    repo.set_many(conn, {TRANSITION_ROLES: json.dumps(overrides)})


def transition_roles(conn, sm, state: str, transition_name: str) -> set[str]:
    """Effective roles allowed for a transition: admin override (DB) wins, then
    the states.yaml roles, then the configured default transition roles."""
    override = transition_role_overrides(conn).get(trans_key(state, transition_name))
    if override:
        return set(override)
    trans = sm.transition(state, transition_name)
    if trans is not None and trans.roles:
        return set(trans.roles)
    return {r.strip() for r in settings.default_transition_roles.split(",") if r.strip()}
