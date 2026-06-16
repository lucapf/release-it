"""RS256 signing key management and JWKS exposure.

Loads the private key from config (PEM) or generates an ephemeral one for dev.
Exposes the matching public key as a JWK so resource servers (the ReleaseIT
backend, or any OIDC client) can verify token signatures.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey,
    RSAPublicKey,
)

from app.config import settings

_private_key: RSAPrivateKey | None = None
_kid: str | None = None


def _b64url_uint(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()


def _load_or_generate() -> RSAPrivateKey:
    if settings.private_key_pem:
        return serialization.load_pem_private_key(
            settings.private_key_pem.encode(), password=None
        )
    # Dev fallback: ephemeral key (tokens invalid after restart).
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def private_key() -> RSAPrivateKey:
    global _private_key
    if _private_key is None:
        _private_key = _load_or_generate()
    return _private_key


def key_id() -> str:
    """Stable key id derived from the public key bytes."""
    global _kid
    if _kid is None:
        pub_bytes = private_key().public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        _kid = hashlib.sha256(pub_bytes).hexdigest()[:16]
    return _kid


def jwks() -> dict:
    pub: RSAPublicKey = private_key().public_key()
    numbers = pub.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": key_id(),
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }
