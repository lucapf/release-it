"""Caller identity — derived from the trusted gateway, NOT validated here.

The backend is no longer a JWT resource server: token signature/expiry checks
and the static role gates now live in the auth service (POST /auth) and the
shared authorization policy, enforced at the edge (the frontend nginx
auth_request). After a request is authorized there, the gateway injects the
caller's identity downstream as headers:

    X-Auth-Subject : the authenticated username (``sub``)
    X-Auth-Roles   : comma-separated ReleaseIT roles

This module simply reads those headers. It performs no cryptographic
verification — it trusts the gateway. The roles are still used for the few
*dynamic* checks the static policy can't express (e.g. per-transition roles,
which are workflow-configured at runtime).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Header

# ReleaseIT roles (docs/release-it.md) — domain constants, reused across the app.
ROLE_DEVELOPER = "Developer"
ROLE_RELEASE_MANAGER = "Release Manager"
ROLE_QA_MANAGER = "QA Manager"
ROLE_ADMIN = "Administrator"
ALL_ROLES = {ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_QA_MANAGER, ROLE_ADMIN}


@dataclass
class Principal:
    subject: str
    roles: set[str] = field(default_factory=set)

    def has_any(self, roles: set[str]) -> bool:
        return bool(self.roles & roles)


def current_principal(
    x_auth_subject: str | None = Header(default=None),
    x_auth_roles: str | None = Header(default=None),
) -> Principal:
    """The caller, as asserted by the gateway. Defaults to an anonymous
    principal when the headers are absent (e.g. direct in-cluster calls)."""
    roles = {r.strip() for r in (x_auth_roles or "").split(",") if r.strip()}
    return Principal(subject=(x_auth_subject or "system"), roles=roles)
