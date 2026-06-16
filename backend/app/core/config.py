"""Application configuration via environment variables.

All settings are read from the environment (or a local ``.env`` file) using
pydantic-settings. See ``deploy/docker-compose.yml`` for the dev defaults.
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
    states_config_path: str = "app/config/states.yaml"

    # --- Integrations (optional, token auth) --------------------------------
    jira_enabled: bool = False
    jira_base_url: str = ""
    jira_token: str = ""

    gitlab_enabled: bool = False
    gitlab_base_url: str = ""
    gitlab_token: str = ""

    awx_enabled: bool = False
    awx_base_url: str = ""
    awx_token: str = ""

    cors_origins: str = "*"


settings = Settings()
