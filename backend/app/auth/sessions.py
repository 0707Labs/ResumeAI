"""Opaque database sessions.

The cookie holds a random token; auth_sessions stores only its sha256. Sessions
slide (30 days from last use) up to an absolute cap of 90 days from creation,
and are revoked instantly by deleting the row. Every sign-in rotates: the old
session row is deleted and a new token and CSRF cookie are issued."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cookies import clear_cookie, csrf_cookie, read_cookie, session_cookie, set_cookie
from app.auth.csrf import issue_csrf
from app.auth.events import log_auth_event
from app.auth.tokens import hash_token, new_token
from app.db.models import AuthSession, User

SLIDING = timedelta(days=30)
ABSOLUTE = timedelta(days=90)
TOUCH_EVERY = timedelta(hours=1)  # don't write on every request


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class SignedIn:
    user: User
    token_hash: str


async def start_session(
    db: AsyncSession,
    request: Request,
    response: Response,
    user: User,
    provider: str | None = None,
) -> None:
    """Sign `user` in: drop the request's existing session (rotation), store a new
    one, set the session and a fresh CSRF cookie, and commit."""
    old = read_cookie(request, session_cookie())
    if old:
        await db.execute(delete(AuthSession).where(AuthSession.session_token_hash == hash_token(old)))
    token = new_token()
    now = _now()
    db.add(AuthSession(
        session_token_hash=hash_token(token),
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + SLIDING,
    ))
    user.last_login_at = now
    await db.commit()
    set_cookie(response, session_cookie(), token, max_age=int(SLIDING.total_seconds()))
    issue_csrf(response)
    log_auth_event("login", user_id=user.id, provider=provider)


async def resolve_session(db: AsyncSession, request: Request) -> SignedIn | None:
    """The live session and user behind the request's cookie, or None.
    Expired sessions and sessions of deleted users are removed on sight."""
    token = read_cookie(request, session_cookie())
    if not token:
        return None
    token_hash = hash_token(token)
    row = (await db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(AuthSession.session_token_hash == token_hash)
    )).one_or_none()
    if row is None:
        return None
    session, user = row
    now = _now()
    if session.expires_at <= now or user.deleted_at is not None:
        await db.execute(delete(AuthSession).where(AuthSession.session_token_hash == token_hash))
        await db.commit()
        log_auth_event("session_expired", user_id=user.id)
        return None
    if now - session.last_seen_at >= TOUCH_EVERY:
        await db.execute(
            update(AuthSession)
            .where(AuthSession.session_token_hash == token_hash)
            .values(last_seen_at=now, expires_at=min(now + SLIDING, session.created_at + ABSOLUTE))
        )
        await db.commit()
    return SignedIn(user=user, token_hash=token_hash)


async def end_session(db: AsyncSession, request: Request, response: Response) -> uuid.UUID | None:
    """Delete the request's session (if any), clear auth cookies. Returns the user id."""
    user_id = None
    token = read_cookie(request, session_cookie())
    if token:
        user_id = (await db.execute(
            delete(AuthSession)
            .where(AuthSession.session_token_hash == hash_token(token))
            .returning(AuthSession.user_id)
        )).scalar_one_or_none()
        await db.commit()
    clear_cookie(response, session_cookie())
    clear_cookie(response, csrf_cookie())
    return user_id
