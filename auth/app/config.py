"""releaseit-auth configuration."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AUTH_", extra="ignore")

    database_url: str = "postgresql://auth:auth@localhost:5433/auth"
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
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin"

    migrations_dir: str = "migrations"
    cors_origins: str = "*"


settings = Settings()
