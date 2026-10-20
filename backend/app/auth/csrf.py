"""CSRF defence for state-changing auth and account requests.

Cookies are SameSite=Lax already; on top, every non-GET must come from our own
origin and echo the CSRF cookie in X-CSRF-Token (double submit). The OAuth
callback is a GET and is covered by its `state` parameter instead."""

import hmac
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response

from app.auth.cookies import csrf_cookie, read_cookie, set_cookie
from app.auth.events import log_auth_event
from app.auth.tokens import new_token
from app.config import get_settings

CSRF_HEADER = "X-CSRF-Token"
CSRF_MAX_AGE = 60 * 60 * 24 * 90
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def _same_origin(request: Request) -> bool:
    expected = get_settings().public_url
    origin = request.headers.get("origin")
    if origin is not None:
        return origin == expected
    referer = request.headers.get("referer")
    return referer is not None and _origin_of(referer) == expected


def _reject(reason: str) -> HTTPException:
    log_auth_event("csrf_rejected", outcome="denied", reason=reason)
    return HTTPException(status_code=403, detail="csrf_failed")


def require_csrf(request: Request) -> None:
    """FastAPI dependency for every state-changing auth/account endpoint."""
    if request.method in SAFE_METHODS:
        return
    if not _same_origin(request):
        raise _reject("origin")
    cookie = read_cookie(request, csrf_cookie())
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise _reject("token")


def issue_csrf(response: Response) -> str:
    """Set a fresh CSRF cookie. Readable by our JS (that's the double submit)."""
    token = new_token()
    set_cookie(response, csrf_cookie(), token, max_age=CSRF_MAX_AGE, http_only=False)
    return token
