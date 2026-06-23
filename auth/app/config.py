"""releaseit-auth configuration."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AUTH_", extra="ignore")

    # Shared ReleaseIT Postgres: the `auth` role's search_path is pinned to the
    # `auth` schema, so this service's tables stay segregated from the backend's.
    database_url: str = "postgresql://auth:auth@localhost:5432/releaseit"
    db_pool_min_size: int = 1
    db_pool_max_size: int = 5

    # Token settings — must match the backend's JWT_ISSUER / JWT_AUDIENCE.
    issuer: str = "http://localhost:8001"
    audience: str = "releaseit"
    access_token_ttl_seconds: int = 3600
    role_claim: str = "roles"

    # RS256 signing key (PEM). If empty, an ephemeral key is generated at
    # startup (dev only — tokens won't survive a restart). In production mount
    # a stable private key via this env var / secret.
    private_key_pem: str = ""

    # Bootstrap admin (created on first migration/seed if no users exist).
    # The password has NO default on purpose: the service refuses to seed an
    # admin unless a strong AUTH_BOOTSTRAP_ADMIN_PASSWORD is supplied, so a
    # fresh deployment can't be taken over with guessable credentials.
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = ""
    # Escape hatch for local/dev only: when true, the guard against weak/guessable
    # bootstrap passwords is skipped so trivial credentials (e.g. admin/admin) can
    # be seeded. Never enable this in a real deployment.
    allow_insecure_bootstrap: bool = False

    migrations_dir: str = "migrations"
    cors_origins: str = "*"


settings = Settings()
