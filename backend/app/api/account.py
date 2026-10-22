"""/app/profile: linked login methods and account deletion.

Connecting Google/GitHub starts at GET /api/auth/{provider}/start?intent=link
(app/api/oauth.py); adding email sign-in sends a magic link bound to this user."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.signin import FIFTEEN_MIN, Accepted, EmailIn, per_key_limit, send_magic_link
from app.auth import oauth
from app.auth.account import AccountError, delete_account, list_accounts, unlink
from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.events import log_auth_event
from app.auth.ratelimit import rate_limit
from app.auth.sessions import end_session
from app.auth.signing import ip_ref, subject_ref
from app.auth.signup import current_notices
from app.db.models import ConsentNotice, ConsentRecord, User
from app.db.rls import service_scope
from app.db.session import get_db
from app.profile.export import export_user

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
    async with service_scope(db):  # email_tokens belong to the sign-in flow, not to the user
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


# --- privacy: consent history, the optional research consent, export ---------------------------


class ConsentEntry(BaseModel):
    purpose: Literal["service", "research", "age_18_plus", "waitlist"]
    action: Literal["granted", "withdrawn"]
    method: str
    notice_version: str
    notice_url: str
    at: datetime


class Consents(BaseModel):
    history: list[ConsentEntry]  # newest first
    research: bool  # the optional "help improve the product" consent, now
    research_available: bool  # a research notice is published, so it can be granted


async def _research_now(db: AsyncSession, user_id: uuid.UUID) -> bool:
    action = await db.scalar(text("SELECT action FROM current_consents WHERE user_id = :u AND purpose = 'research'"),
                             {"u": user_id})
    return action == "granted"


@router.get("/consents")
async def consents(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> Consents:
    rows = (await db.execute(
        select(ConsentRecord, ConsentNotice).join(ConsentNotice, ConsentNotice.id == ConsentRecord.notice_id)
        .where(ConsentRecord.user_id == user.id).order_by(ConsentRecord.id.desc()).limit(200))).all()
    return Consents(
        history=[ConsentEntry(purpose=c.purpose, action=c.action, method=c.method, notice_version=n.version,
                              notice_url=n.body_url, at=c.created_at) for c, n in rows],
        research=await _research_now(db, user.id),
        research_available="research" in await current_notices(db))


class ResearchIn(BaseModel):
    granted: bool


@router.put("/consents/research", dependencies=[Depends(rate_limit("consent_change", 10, 60)), Depends(require_csrf)])
async def set_research(body: ResearchIn, request: Request, user: User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)) -> Consents:
    """Grant or withdraw the optional research consent. Recorded against the current notice
    (append-only, like every consent); asking for the state it's already in records nothing."""
    if await _research_now(db, user.id) != body.granted:
        notice = (await current_notices(db)).get("research")
        if notice is None:
            raise HTTPException(status_code=409, detail="no_research_notice")
        db.add(ConsentRecord(user_id=user.id, subject_ref=subject_ref(user.email), notice_id=notice.id,
                             purpose="research", action="granted" if body.granted else "withdrawn",
                             method="account_settings",
                             ip_hmac=ip_ref(request.client.host if request.client else None)))
        await db.commit()
    return await consents(user, db)


@router.post("/export", dependencies=[Depends(rate_limit("data_export", 3, 3600)), Depends(require_csrf)])
async def export(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Everything we hold about you, as a JSON file (see app.profile.export)."""
    doc = await export_user(db, user)
    log_auth_event("data_exported", user_id=user.id)
    name = f"resume-tailor-export-{datetime.now(UTC):%Y%m%d}.json"
    return JSONResponse(jsonable_encoder(doc), headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
