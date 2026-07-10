"""External authorization for POST /auth.

Given a requested URL, an HTTP method and a JWT, decide whether the request is
allowed:

  check 1 — the JWT is correctly signed (RS256, this service's key);
  check 2 — the JWT is not expired (and matches issuer/audience);
  check 3 — the (method, path) is permitted for the caller's role(s) by a
            role-based policy loaded from a configMap-mounted YAML file.

The policy is a first-match-wins list of rules. A request is authorized when the
first rule matching its (method, path) grants one of the caller's roles; if no
rule matches, the request is denied (default deny).
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import jwt
import yaml

from app.config import settings
from app.keys import private_key

# Bundled default policy, used when AUTH_AUTHZ_POLICY_FILE is unset (local/dev
# and tests). In the cluster the Helm chart mounts a configMap and points
# AUTH_AUTHZ_POLICY_FILE at it.
_DEFAULT_POLICY_FILE = Path(__file__).with_name("authz_policy.yaml")


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern
    methods: frozenset[str]  # uppercased HTTP methods; {"*"} = any method
    roles: frozenset[str]    # allowed roles; {"*"} = any authenticated principal

    def matches(self, method: str, path: str) -> bool:
        if "*" not in self.methods and method not in self.methods:
            return False
        return self.pattern.fullmatch(path) is not None

    def grants(self, roles: set[str]) -> bool:
        return "*" in self.roles or bool(self.roles & roles)


@dataclass(frozen=True)
class Policy:
    rules: tuple[Rule, ...]

    def allows(self, method: str, path: str, roles: set[str]) -> bool:
        for rule in self.rules:
            if rule.matches(method, path):
                return rule.grants(roles)  # first match decides
        return False  # default deny


def _compile_pattern(pattern: str) -> re.Pattern:
    """Translate a path glob into a regex.

    ``*`` matches a single path segment, ``**`` matches any (possibly empty)
    suffix; every other character is matched literally.
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern[i] == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]+")
        else:
            out.append(re.escape(pattern[i]))
        i += 1
    return re.compile("".join(out))


def _parse_policy(text: str) -> Policy:
    data = yaml.safe_load(text) or {}
    rules: list[Rule] = []
    for raw in data.get("rules", []):
        methods = raw.get("methods", ["*"])
        if isinstance(methods, str):
            methods = [methods]
        roles = raw.get("roles", [])
        if isinstance(roles, str):
            roles = [roles]
        rules.append(
            Rule(
                pattern=_compile_pattern(str(raw["path"])),
                methods=frozenset(m.upper() for m in methods),
                roles=frozenset(roles),
            )
        )
    return Policy(rules=tuple(rules))


_lock = threading.Lock()
_cache: tuple[float, Policy] | None = None


def _policy_path() -> Path:
    # Use the configured (configMap-mounted) policy when present; otherwise fall
    # back to the bundled default so the service runs even without the configMap.
    if settings.authz_policy_file:
        configured = Path(settings.authz_policy_file)
        if configured.exists():
            return configured
    return _DEFAULT_POLICY_FILE


def load_policy() -> Policy:
    """Load (and cache) the policy, reloading if the file changed on disk so a
    configMap update is picked up without restarting the pod."""
    global _cache
    path = _policy_path()
    mtime = path.stat().st_mtime
    with _lock:
        if _cache is None or _cache[0] != mtime:
            _cache = (mtime, _parse_policy(path.read_text()))
        return _cache[1]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    subject: str = ""
    roles: tuple[str, ...] = ()


def _decode(token: str) -> dict | None:
    """Checks 1 & 2: decode + verify the token (signature, expiry, iss, aud).
    Returns the claims, or ``None`` if the token is invalid."""
    if not token:
        return None
    try:
        return jwt.decode(
            token,
            private_key().public_key(),
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=settings.issuer,
        )
    except jwt.PyJWTError:
        # Covers bad signature, expiry, wrong issuer/audience, malformed token.
        return None


def _roles_of(claims: dict) -> list[str]:
    roles = claims.get(settings.role_claim, [])
    return [roles] if isinstance(roles, str) else list(roles)


def validate_token(token: str) -> set[str] | None:
    """Return the caller's roles if the token is valid, else ``None``."""
    claims = _decode(token)
    return None if claims is None else set(_roles_of(claims))


def decide(method: str, url: str, token: str) -> Decision:
    """Run all three checks. On success the Decision also carries the caller's
    subject and roles so the gateway can propagate them downstream."""
    claims = _decode(token)  # checks 1 & 2
    if claims is None:
        return Decision(False)
    roles = _roles_of(claims)
    path = urlsplit(url).path or url  # match on the path only (ignore host/query)
    allowed = load_policy().allows(method.upper(), path, set(roles))  # check 3
    return Decision(allowed, subject=str(claims.get("sub", "")), roles=tuple(roles))


def authorize(method: str, url: str, token: str) -> bool:
    """Convenience boolean wrapper around :func:`decide`."""
    return decide(method, url, token).allowed
