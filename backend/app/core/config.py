"""Application configuration via environment variables.

All settings are read from the environment (or a local ``.env`` file) using
pydantic-settings. The defaults below target a local Postgres; the Helm charts
under ``deploy/`` override them for the cluster.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # --- Database -----------------------------------------------------------
    database_url: str = "postgresql://releaseit:releaseit@localhost:5432/releaseit"
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10

    # --- Feature flags ------------------------------------------------------
    solution_enabled: bool = True

    # --- Auth (JWT resource server) -----------------------------------------
    # The backend never issues tokens; it only verifies them against the
    # configured provider's JWKS. Point these at releaseit-auth or any
    # OIDC-compliant engine (Keycloak, Auth0, ...).
    jwt_issuer: str = "http://localhost:8001"
    jwt_audience: str = "releaseit"
    jwt_jwks_url: str = "http://localhost:8001/.well-known/jwks.json"
    jwt_role_claim: str = "roles"
    # Allow disabling auth for local development / tests only.
    auth_enabled: bool = True

    # --- Release state machine ---------------------------------------------
    # The workflow graph is database-backed (seeded by the workflow migration).
    # Roles allowed to perform a transition that does not declare its own
    # ``roles`` in the workflow definition. Comma-separated.
    default_transition_roles: str = "QA Manager,Release Manager,Administrator"

    # --- Release readiness rules -------------------------------------------
    # Documentation a release must carry before it is considered complete,
    # as ``Label=keyword`` pairs (keyword matched case-insensitively against
    # the published — non-draft — document file names). Comma-separated.
    required_docs: str = "Release Notes=release-notes,Installation Guide=install"
    # Jira issue statuses that count as "closed". Everything else is open.
    closed_bug_statuses: str = "Done"

    # --- Issue tracker ------------------------------------------------------
    # Active issue tracker: "jira" or "github". These are the seed defaults;
    # the runtime configuration page (app_config table) overrides them.
    tracker_provider: str = "jira"

    # --- Integrations (optional, token auth) --------------------------------
    jira_enabled: bool = False
    jira_base_url: str = ""
    jira_token: str = ""

    github_enabled: bool = False
    github_base_url: str = "https://api.github.com"
    github_repo: str = ""  # "owner/repo"
    github_token: str = ""

    # --- LLM (release-note generation) -------------------------------------
    # Engine: "claude" (Anthropic API) or "ollama" (local server). Seed
    # defaults; the configuration page (app_config) overrides them at runtime.
    llm_provider: str = "claude"
    claude_api_key: str = ""
    claude_model: str = "claude-opus-4-8"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    gitlab_enabled: bool = False
    gitlab_base_url: str = ""
    gitlab_token: str = ""

    awx_enabled: bool = False
    awx_base_url: str = ""
    awx_token: str = ""

    cors_origins: str = "*"


settings = Settings()
