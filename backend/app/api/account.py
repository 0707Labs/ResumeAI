"""/account: linked login methods and account deletion.

Connecting Google/GitHub starts at GET /api/auth/{provider}/start?intent=link
(app/api/oauth.py); adding email sign-in sends a magic link bound to this user."""

import hashlib
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.signin import FIFTEEN_MIN, Accepted, EmailIn, per_key_limit, send_magic_link
from app.auth import oauth
from app.auth.account import AccountError, delete_account, list_accounts, unlink
from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.events import log_auth_event
from app.auth.ratelimit import rate_limit
from app.auth.sessions import end_session
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/account")


class LinkedAccount(BaseModel):
    id: uuid.UUID
    provider: Literal["google", "github", "email"]
    email: str  # the verified email when it was linked
    linked_at: datetime


class Providers(BaseModel):
    accounts: list[LinkedAccount]
    can_unlink: bool  # false when only one login method is left
    available: dict[Literal["google", "github", "email"], bool]  # can be connected right now


class DeleteIn(BaseModel):
    confirm: Literal[True]


@router.get("/providers")
async def providers(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> Providers:
    accounts = await list_accounts(db, user.id)
    return Providers(
        accounts=[LinkedAccount(id=a.id, provider=a.provider, email=a.email_at_link, linked_at=a.created_at)
                  for a in accounts],
        can_unlink=len(accounts) > 1,
        available={"google": oauth.credentials("google") is not None,
                   "github": oauth.credentials("github") is not None,
                   "email": True},
    )


@router.delete("/providers/{account_id}", status_code=204,
               dependencies=[Depends(rate_limit("unlink", 10, 60)), Depends(require_csrf)])
async def remove_provider(account_id: uuid.UUID, user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)) -> None:
    """Refused (409 last_login_method) when it is the only way left to sign in."""
    try:
        provider = await unlink(db, user.id, account_id)
    except AccountError as exc:
        raise HTTPException(status_code=404 if exc.code == "not_found" else 409, detail=exc.code) from None
    log_auth_event("account_unlinked", user_id=user.id, provider=provider)


@router.post("/email/link", status_code=202,
             dependencies=[Depends(rate_limit("email_start", 5, FIFTEEN_MIN)), Depends(require_csrf)])
async def link_email(body: EmailIn, user: User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)) -> Accepted:
    """Email a link that adds email sign-in for this address to this account."""
    per_key_limit(f"email_addr:{hashlib.sha256(body.email.encode()).hexdigest()}", 3, FIFTEEN_MIN)
    await send_magic_link(db, body.email, "link", user_id=user.id)
    return Accepted()


@router.post("/delete", status_code=204,
             dependencies=[Depends(rate_limit("account_delete", 3, 60)), Depends(require_csrf)])
async def delete(body: DeleteIn, request: Request, response: Response, user: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)) -> None:
    """Delete the account: login methods, sessions and pending sign-ins go now."""
    user_id = user.id
    await delete_account(db, user)
    await end_session(db, request, response)
    log_auth_event("account_deleted", user_id=user_id)
