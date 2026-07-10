"""releaseit-auth — default JWT/OIDC provider and user-management service.

Swappable for any OIDC-compliant engine (Keycloak, Auth0, ...): the ReleaseIT
backend only needs this service's issuer, audience and JWKS URL.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app import authz
from app.config import settings
from app.db import apply_migrations, close_pool, connection, open_pool
from app.keys import jwks
from app.security import hash_password
from app.user_management import router as user_router
from app import users_repo

log = logging.getLogger("releaseit.auth")


# Passwords too weak/guessable to ever seed an admin account with.
_INSECURE_BOOTSTRAP_PASSWORDS = {"", "admin", "password", "changeme", "secret"}
_MIN_BOOTSTRAP_PASSWORD_LEN = 12


def _bootstrap_admin() -> None:
    """Create a default Administrator on first run (no users yet).

    Fails closed: refuses to seed the admin with a missing or insecure password
    so a fresh deployment can't be taken over with guessable credentials. Set a
    strong AUTH_BOOTSTRAP_ADMIN_PASSWORD (>= 12 chars) before first run.
    """
    with connection() as conn:
        if users_repo.count_users(conn) == 0:
            password = settings.bootstrap_admin_password
            if not settings.allow_insecure_bootstrap and (
                password.lower() in _INSECURE_BOOTSTRAP_PASSWORDS
                or len(password) < _MIN_BOOTSTRAP_PASSWORD_LEN
            ):
                raise RuntimeError(
                    "Refusing to bootstrap the admin user with a missing or "
                    "insecure password. Set AUTH_BOOTSTRAP_ADMIN_PASSWORD to a "
                    "strong value (at least 12 characters, not a common default)."
                )
            user = users_repo.create_user(
                conn,
                settings.bootstrap_admin_username,
                None,
                hash_password(password),
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

# Never combine a wildcard origin with credentials (any site could then make
# credentialed cross-origin requests). Credentials require an explicit allow-list.
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_router, prefix="/api/v1/user-management", tags=["user-management"])


@app.api_route("/auth", methods=["GET", "POST"], tags=["authz"])
async def authorize_request(request: Request) -> Response:
    """External authorization endpoint.

    Validates the JWT (signature + expiry) and checks the requested
    (method, url) against the role policy. Returns 200 if authorized, 403 if not.

    Inputs are taken from (in order):
      * a JSON body ``{url, method, token, ...}`` — for direct/API callers
        (extra parameters are accepted and ignored);
      * the ``X-Original-Method`` / ``X-Original-URI`` headers and the
        ``Authorization`` bearer header — set by an nginx ``auth_request`` /
        ingress forward-auth subrequest.

    On a 200 the caller's identity is returned as ``X-Auth-Subject`` and
    ``X-Auth-Roles`` headers, which the gateway propagates to the upstream
    service (the backend trusts these instead of validating the token itself).
    """
    body: dict = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}

    method = body.get("method") or request.headers.get("x-original-method") or "GET"
    url = (
        body.get("url")
        or request.headers.get("x-original-uri")
        or request.headers.get("x-original-url")
        or ""
    )
    token = body.get("token")
    if not token:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()

    decision = authz.decide(method, url, token or "")
    if not decision.allowed:
        # Log every denial (a "lack of permissions" event) so it is auditable.
        # The path only — never the token or query string — is recorded.
        if decision.subject:
            reason = (
                f"caller '{decision.subject}' with roles "
                f"[{', '.join(decision.roles) or 'none'}] is not permitted"
            )
        else:
            reason = "missing, invalid or expired token"
        log.warning("authorization denied: %s %s — %s", method, urlsplit(url).path or url, reason)
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    return Response(
        status_code=status.HTTP_200_OK,
        headers={
            "X-Auth-Subject": decision.subject,
            "X-Auth-Roles": ",".join(decision.roles),
        },
    )


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
