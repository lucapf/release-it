"""releaseit-auth — default JWT/OIDC provider and user-management service.

Swappable for any OIDC-compliant engine (Keycloak, Auth0, ...): the ReleaseIT
backend only needs this service's issuer, audience and JWKS URL.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import apply_migrations, close_pool, connection, open_pool
from app.keys import jwks
from app.security import hash_password
from app.user_management import router as user_router
from app import users_repo


def _bootstrap_admin() -> None:
    """Create a default Administrator on first run (no users yet)."""
    with connection() as conn:
        if users_repo.count_users(conn) == 0:
            user = users_repo.create_user(
                conn,
                settings.bootstrap_admin_username,
                None,
                hash_password(settings.bootstrap_admin_password),
            )
            users_repo.assign_role(conn, user["id"], "Administrator")
            conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    apply_migrations()
    _bootstrap_admin()
    try:
        yield
    finally:
        close_pool()


app = FastAPI(title="releaseit-auth", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_router, prefix="/api/v1/user-management", tags=["user-management"])


@app.get("/.well-known/jwks.json", tags=["oidc"])
def jwks_endpoint() -> dict:
    return jwks()


@app.get("/.well-known/openid-configuration", tags=["oidc"])
def openid_configuration() -> dict:
    return {
        "issuer": settings.issuer,
        "jwks_uri": f"{settings.issuer}/.well-known/jwks.json",
        "token_endpoint": f"{settings.issuer}/api/v1/user-management/login",
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
