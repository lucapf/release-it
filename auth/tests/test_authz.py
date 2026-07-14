"""Auth service: external authorization (POST /auth) — token checks + policy."""
from __future__ import annotations

import datetime as dt

import jwt
import pytest
from fastapi.testclient import TestClient

from app import authz
from app.authz import _compile_pattern, _parse_policy
from app.config import settings
from app.keys import key_id, private_key
from app.main import app
from app.security import issue_token

client = TestClient(app)  # no context manager => lifespan/DB not started


def _token(sub: str, roles: list[str], *, exp_delta_s: int = 3600) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    claims = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "sub": sub,
        "iat": now,
        "exp": now + dt.timedelta(seconds=exp_delta_s),
        settings.role_claim: roles,
    }
    return jwt.encode(claims, private_key(), algorithm="RS256", headers={"kid": key_id()})


# --- policy matching -------------------------------------------------------

def test_compile_pattern_segment_vs_suffix():
    assert _compile_pattern("/a/*").fullmatch("/a/b")
    assert not _compile_pattern("/a/*").fullmatch("/a/b/c")  # * = one segment
    assert _compile_pattern("/a/**").fullmatch("/a/b/c")     # ** = any suffix
    assert _compile_pattern("/a/**").fullmatch("/a/")


def test_policy_first_match_wins_and_default_deny():
    policy = _parse_policy(
        """
        rules:
          - { path: "/api/v1/users", methods: "*", roles: ["Administrator"] }
          - { path: "/api/v1/**",    methods: ["GET"], roles: ["Developer", "Administrator"] }
        """
    )
    # First (admin-only) rule wins for the users path even though the generic
    # GET rule below would have allowed a Developer.
    assert policy.allows("GET", "/api/v1/users", {"Administrator"})
    assert not policy.allows("GET", "/api/v1/users", {"Developer"})
    # Generic read rule.
    assert policy.allows("GET", "/api/v1/product", {"Developer"})
    assert not policy.allows("POST", "/api/v1/product", {"Developer"})  # no matching rule
    assert not policy.allows("GET", "/somewhere/else", {"Administrator"})  # default deny


def test_policy_wildcard_roles_allow_any_authenticated():
    policy = _parse_policy('rules:\n  - { path: "/x", methods: "*", roles: "*" }')
    assert policy.allows("GET", "/x", {"Developer"})
    assert policy.allows("DELETE", "/x", set())  # any authenticated principal


# --- token validation (checks 1 & 2) ---------------------------------------

def test_validate_token_valid_returns_roles():
    assert authz.validate_token(_token("alice", ["Developer"])) == {"Developer"}


def test_validate_token_rejects_expired():
    assert authz.validate_token(_token("alice", ["Administrator"], exp_delta_s=-10)) is None


def test_validate_token_rejects_tampered_signature():
    tok = _token("alice", ["Administrator"])
    tampered = tok[:-3] + ("aaa" if not tok.endswith("aaa") else "bbb")
    assert authz.validate_token(tampered) is None


def test_validate_token_rejects_empty_and_garbage():
    assert authz.validate_token("") is None
    assert authz.validate_token("not.a.jwt") is None


# --- end-to-end authorize() against the bundled default policy --------------

def test_authorize_with_default_policy():
    admin = _token("root", ["Administrator"])
    dev = _token("dev", ["Developer"])
    qa = _token("qa", ["QA Manager"])

    # Reads allowed for any role; writes per role.
    assert authz.authorize("GET", "/api/v1/product", dev)
    assert authz.authorize("POST", "/api/v1/product", dev)
    assert not authz.authorize("POST", "/api/v1/product", qa)
    assert not authz.authorize("DELETE", "/api/v1/product/7", dev)
    assert authz.authorize("DELETE", "/api/v1/product/7", admin)
    # Deleting a release document: Release Managers and Administrators only
    # (the multi-segment path isn't covered by the /release/* delete rule).
    rm = _token("rm", ["Release Manager"])
    assert authz.authorize("DELETE", "/api/v1/release/3/documents/5", rm)
    assert authz.authorize("DELETE", "/api/v1/release/3/documents/5", admin)
    assert not authz.authorize("DELETE", "/api/v1/release/3/documents/5", dev)
    assert not authz.authorize("DELETE", "/api/v1/release/3/documents/5", qa)
    # Git repository links: Administrators configure them; everyone may read.
    assert authz.authorize("POST", "/api/v1/product/7/git-repos", admin)
    assert not authz.authorize("POST", "/api/v1/product/7/git-repos", dev)
    assert authz.authorize("PATCH", "/api/v1/product/7/git-repos/2", admin)
    assert authz.authorize("DELETE", "/api/v1/product/7/git-repos/2", admin)
    assert not authz.authorize("DELETE", "/api/v1/product/7/git-repos/2",
                               _token("rm2", ["Release Manager"]))
    assert authz.authorize("GET", "/api/v1/product/7/git-repos", dev)
    # User management is admin-only, even for reads.
    assert not authz.authorize("GET", "/api/v1/user-management/users", dev)
    assert authz.authorize("GET", "/api/v1/user-management/users", admin)
    # Host + query string in the URL are ignored (path is what matters).
    assert authz.authorize("GET", "http://releaseit.local/api/v1/product?page=2", dev)
    # Expired token never authorizes.
    assert not authz.authorize("GET", "/api/v1/product", _token("x", ["Administrator"], exp_delta_s=-1))


# --- the POST /auth endpoint -----------------------------------------------

def test_endpoint_authorized_returns_200():
    r = client.post("/auth", json={
        "url": "/api/v1/product", "method": "GET", "token": _token("dev", ["Developer"]),
    })
    assert r.status_code == 200


def test_endpoint_forbidden_returns_403():
    r = client.post("/auth", json={
        "url": "/api/v1/product/3", "method": "DELETE", "token": _token("dev", ["Developer"]),
    })
    assert r.status_code == 403


def test_policy_denial_is_logged_with_subject(caplog):
    with caplog.at_level("WARNING", logger="releaseit.auth"):
        r = client.post("/auth", json={
            "url": "/api/v1/product/3", "method": "DELETE", "token": _token("dev", ["Developer"]),
        })
    assert r.status_code == 403
    msgs = [rec.getMessage() for rec in caplog.records]
    assert any("authorization denied" in m and "DELETE" in m and "dev" in m for m in msgs)


def test_invalid_token_denial_is_logged(caplog):
    with caplog.at_level("WARNING", logger="releaseit.auth"):
        r = client.post("/auth", json={"url": "/api/v1/product", "method": "GET"})
    assert r.status_code == 403
    assert any("missing, invalid or expired token" in rec.getMessage() for rec in caplog.records)


def test_endpoint_accepts_token_via_authorization_header():
    tok = _token("root", ["Administrator"])
    r = client.post(
        "/auth",
        json={"url": "/api/v1/user-management/users", "method": "GET"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200


def test_endpoint_missing_token_is_forbidden():
    r = client.post("/auth", json={"url": "/api/v1/product", "method": "GET"})
    assert r.status_code == 403


def test_endpoint_ignores_additional_parameters():
    r = client.post("/auth", json={
        "url": "/api/v1/product", "method": "GET", "token": _token("dev", ["Developer"]),
        "client_ip": "10.0.0.1", "trace_id": "abc-123",  # extra params accepted
    })
    assert r.status_code == 200


# --- forward-auth (nginx auth_request / ingress) path ----------------------

def test_forward_auth_headers_authorized_sets_identity():
    tok = _token("root", ["Administrator"])
    r = client.get("/auth", headers={
        "X-Original-Method": "DELETE",
        "X-Original-URI": "/api/v1/product/9",
        "Authorization": f"Bearer {tok}",
    })
    assert r.status_code == 200
    assert r.headers.get("X-Auth-Subject") == "root"
    assert "Administrator" in r.headers.get("X-Auth-Roles", "")


def test_forward_auth_headers_forbidden():
    tok = _token("dev", ["Developer"])
    r = client.get("/auth", headers={
        "X-Original-Method": "DELETE",            # Developer can't delete products
        "X-Original-URI": "/api/v1/product/9",
        "Authorization": f"Bearer {tok}",
    })
    assert r.status_code == 403
