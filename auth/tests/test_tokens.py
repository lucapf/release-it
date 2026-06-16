"""Auth service: password hashing and JWT issuance/verification via JWKS."""
from __future__ import annotations

import json

import jwt

from app.keys import jwks
from app.security import hash_password, issue_token, verify_password


def test_password_hash_roundtrip():
    h = hash_password("s3cret")
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)


def test_issue_token_verifiable_with_jwks():
    """A resource server must be able to verify our token using only the JWKS."""
    token = issue_token("alice", ["Developer"])
    jwk = jwks()["keys"][0]
    key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
    claims = jwt.decode(
        token, key, algorithms=["RS256"], audience="releaseit",
        issuer="http://localhost:8001",
    )
    assert claims["sub"] == "alice"
    assert claims["roles"] == ["Developer"]


def test_tampered_token_rejected():
    token = issue_token("alice", ["Developer"])
    jwk = jwks()["keys"][0]
    key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    try:
        jwt.decode(tampered, key, algorithms=["RS256"], audience="releaseit",
                   issuer="http://localhost:8001")
        assert False, "tampered token should not verify"
    except jwt.PyJWTError:
        pass
