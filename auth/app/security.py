"""Password hashing and RS256 JWT issuance."""
from __future__ import annotations

import datetime as _dt

import bcrypt
import jwt

from app.config import settings
from app.keys import key_id, private_key


def hash_password(plain: str) -> str:
    # bcrypt operates on a max of 72 bytes; encode and let bcrypt handle salting.
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def issue_token(subject: str, roles: list[str]) -> str:
    now = _dt.datetime.now(_dt.timezone.utc)
    claims = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "sub": subject,
        "iat": now,
        "exp": now + _dt.timedelta(seconds=settings.access_token_ttl_seconds),
        settings.role_claim: roles,
    }
    return jwt.encode(
        claims,
        private_key(),
        algorithm="RS256",
        headers={"kid": key_id()},
    )
