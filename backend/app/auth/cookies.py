"""Auth cookie names and attributes.

Over https the names carry the __Host- prefix (Secure, Path=/, no Domain, so
no subdomain can set or read them). Plain-http dev origins drop the prefix and
Secure, since some browsers refuse Secure cookies on http://localhost."""

from fastapi import Request, Response

from app.config import get_settings


def _secure() -> bool:
    return get_settings().public_url.startswith("https://")


def cookie_name(base: str) -> str:
    return f"__Host-{base}" if _secure() else base


def session_cookie() -> str:
    return cookie_name("rt_session")


def csrf_cookie() -> str:
    return cookie_name("rt_csrf")


def set_cookie(response: Response, name: str, value: str, *, max_age: int, http_only: bool = True) -> None:
    response.set_cookie(
        name, value, max_age=max_age, path="/", secure=_secure(), httponly=http_only, samesite="lax"
    )


def clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=_secure(), httponly=True, samesite="lax")


def read_cookie(request: Request, name: str) -> str | None:
    return request.cookies.get(name) or None
