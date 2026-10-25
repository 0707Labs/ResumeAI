"""HMAC signing for short-lived cookies and pseudonymous references.

RT_AUTH_SECRET is required unless the public URL is a localhost dev origin,
where a per-process random key is used (restarting the API drops pending sign-ups)."""

import hashlib
import hmac
import secrets
from functools import lru_cache

from app.config import get_settings


@lru_cache
def _dev_key() -> bytes:
    return secrets.token_bytes(32)


def secret_key() -> bytes:
    settings = get_settings()
    if settings.auth_secret:
        return settings.auth_secret.encode()
    if settings.local_origin:
        return _dev_key()
    raise RuntimeError("RT_AUTH_SECRET must be set when RT_PUBLIC_URL is not localhost")


def _mac(purpose: str, value: str) -> str:
    return hmac.new(secret_key(), f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def sign(purpose: str, value: str) -> str:
    return f"{value}.{_mac(purpose, value)}"


def unsign(purpose: str, signed: str | None) -> str | None:
    """The value if the signature is ours for this purpose, else None."""
    if not signed or "." not in signed:
        return None
    value, mac = signed.rsplit(".", 1)
    return value if hmac.compare_digest(mac, _mac(purpose, value)) else None


def subject_ref(email: str) -> str:
    """Stable pseudonym for an email (consent proof that survives account purge)."""
    return _mac("subject", email.lower())


def ip_ref(ip: str | None) -> str | None:
    return _mac("ip", ip) if ip else None
