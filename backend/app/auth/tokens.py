import hashlib
import secrets


def new_token() -> str:
    """32 random bytes, URL-safe. Sent to the browser; never stored as-is."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """What the database stores for any session, pending or email token."""
    return hashlib.sha256(token.encode()).hexdigest()
