"""Session endpoints: who am I, CSRF token, sign out.

Sign-in endpoints live in app/api/signin.py; they all end in
app.auth.sessions.start_session."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import oauth
from app.auth.cookies import csrf_cookie, read_cookie
from app.auth.csrf import issue_csrf, require_csrf
from app.auth.deps import current_user
from app.auth.events import log_auth_event
from app.auth.ratelimit import rate_limit
from app.auth.roles import Capability, Role, capabilities
from app.auth.sessions import end_session
from app.db.models import User
from app.db.session import get_db

router = APIRouter()


class Me(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: Role
    status: Literal["active", "suspended"]
    capabilities: list[Capability]  # what the UI may offer; the API checks again on every call
    onboarded: bool  # false until the first-login wizard is finished or skipped


class CsrfToken(BaseModel):
    csrf_token: str


class ProviderAvailability(BaseModel):
    google: bool
    github: bool
    email: bool = True


@router.get("/api/me")
async def me(user: User = Depends(current_user)) -> Me:
    return Me(id=user.id, email=user.email, name=user.name, role=user.role, status=user.status,
              capabilities=capabilities(user.role), onboarded=user.onboarded_at is not None)


@router.get("/api/auth/providers")
async def providers() -> ProviderAvailability:
    """Which sign-in buttons work right now (OAuth apps configured)."""
    return ProviderAvailability(google=oauth.credentials("google") is not None,
                                github=oauth.credentials("github") is not None)


@router.get("/api/auth/csrf", dependencies=[Depends(rate_limit("csrf", 60, 60))])
async def csrf(request: Request, response: Response) -> CsrfToken:
    """The CSRF token to echo in X-CSRF-Token; sets the cookie if it isn't there yet."""
    token = read_cookie(request, csrf_cookie()) or issue_csrf(response)
    return CsrfToken(csrf_token=token)


@router.post(
    "/api/auth/logout",
    status_code=204,
    dependencies=[Depends(rate_limit("logout", 30, 60)), Depends(require_csrf)],
)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    user_id = await end_session(db, request, response)
    log_auth_event("logout", user_id=user_id)
