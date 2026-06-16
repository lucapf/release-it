"""JWT verification — the backend is a pure resource server.

Tokens are validated against the configured provider's JWKS (releaseit-auth by
default, or any OIDC engine: Keycloak, Auth0, ...). The backend never issues
tokens nor stores passwords. A configurable claim (default ``roles``) is mapped
to ReleaseIT roles for RBAC.
"""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient

from app.core.config import settings

# Cached JWKS client (refreshes keys internally as needed).
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(settings.jwt_jwks_url)
    return _jwks_client


# ReleaseIT roles (docs/release-it.md).
ROLE_DEVELOPER = "Developer"
ROLE_RELEASE_MANAGER = "Release Manager"
ROLE_QA_MANAGER = "QA Manager"
ROLE_ADMIN = "Administrator"
ALL_ROLES = {ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_QA_MANAGER, ROLE_ADMIN}


@dataclass
class Principal:
    subject: str
    roles: set[str]

    def has_any(self, roles: set[str]) -> bool:
        return bool(self.roles & roles)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    """FastAPI dependency: validate the Bearer JWT and return the Principal."""
    if not settings.auth_enabled:
        # Dev/test escape hatch — treat everyone as admin.
        return Principal(subject="dev", roles=set(ALL_ROLES))

    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:  # signature, exp, aud, iss, ...
        raise _unauthorized(f"Invalid token: {exc}") from exc

    raw_roles = claims.get(settings.jwt_role_claim, [])
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    return Principal(subject=str(claims.get("sub", "")), roles=set(raw_roles))


def require_role(*allowed: str):
    """Dependency factory: require the principal to hold one of ``allowed`` roles."""
    allowed_set = set(allowed)

    def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has_any(allowed_set):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(sorted(allowed_set))}",
            )
        return principal

    return _dep
