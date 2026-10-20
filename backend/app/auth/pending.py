"""Pending sign-in identities: who someone is, before they have an account.

The browser holds a signed cookie with a random token; pending_auth stores its
hash. 15 minutes from creation, never extended. A pending identity is never
treated as signed in."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cookies import clear_cookie, cookie_name, read_cookie, set_cookie
from app.auth.events import log_auth_event
from app.auth.signing import sign, unsign
from app.auth.tokens import hash_token, new_token
from app.db.models import PendingAuth

PENDING_TTL = timedelta(minutes=15)
Provider = Literal["google", "github", "email"]


def pending_cookie() -> str:
    return cookie_name("rt_pending")


def _token(request: Request) -> str | None:
    return unsign("pending", read_cookie(request, pending_cookie()))


async def create_pending(
    db: AsyncSession,
    request: Request,
    response: Response,
    *,
    provider: Provider,
    provider_account_id: str,
    verified_email: str | None,
) -> PendingAuth:
    """Replace this browser's pending identity with a new one and commit."""
    old = _token(request)
    if old:
        await db.execute(delete(PendingAuth).where(PendingAuth.token_hash == hash_token(old)))
    token = new_token()
    pending = PendingAuth(
        token_hash=hash_token(token),
        kind="signup" if verified_email else "needs_email",
        provider=provider,
        provider_account_id=provider_account_id,
        verified_email=verified_email,
        expires_at=datetime.now(UTC) + PENDING_TTL,
    )
    db.add(pending)
    await db.commit()
    set_cookie(response, pending_cookie(), sign("pending", token), max_age=int(PENDING_TTL.total_seconds()))
    log_auth_event("pending_created", provider=provider, reason=pending.kind)
    return pending


async def load_pending(db: AsyncSession, request: Request, *, lock: bool = False) -> PendingAuth | None:
    """This browser's live pending identity, or None (missing, tampered, expired)."""
    token = _token(request)
    if not token:
        return None
    query = select(PendingAuth).where(
        PendingAuth.token_hash == hash_token(token), PendingAuth.expires_at > datetime.now(UTC)
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


def clear_pending(response: Response) -> None:
    clear_cookie(response, pending_cookie())
