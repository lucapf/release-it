"""Local token verification for protecting auth-service admin endpoints."""
from __future__ import annotations

import jwt
from fastapi import Header, HTTPException, status

from app.config import settings
from app.keys import private_key

ADMIN_ROLE = "Administrator"


def require_admin(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = jwt.decode(
            token,
            private_key().public_key(),
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=settings.issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc

    roles = claims.get(settings.role_claim, [])
    if isinstance(roles, str):
        roles = [roles]
    if ADMIN_ROLE not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required")
    return str(claims.get("sub", ""))
