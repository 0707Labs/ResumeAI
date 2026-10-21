"""Email magic link and the invite gate.

Flow for someone new:  sign in (magic link now; Google/GitHub next step)
  -> pending identity (cookie, 15 min) -> invite step -> consent step
  -> complete_signup creates the account and signs them in.
No invite: the frontend offers the waitlist, pre-filled from GET /api/auth/pending.

Every state-changing endpoint is rate limited and CSRF-protected. Errors are
short codes the frontend maps to copy (e.g. no_invite -> "No invite found for
this account")."""

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.account import AccountError, link
from app.auth.csrf import require_csrf
from app.auth.events import log_auth_event
from app.auth.identity import AccountUnavailable, resolve_identity
from app.auth.invites import find_bound, find_usable
from app.auth.mailer import get_mailer, magic_link_mail
from app.auth.pending import clear_pending, create_pending, load_pending
from app.auth.ratelimit import limiter, rate_limit
from app.auth.sessions import SignedIn, resolve_session, start_session
from app.auth.signup import SignupError, complete_signup, current_notices
from app.auth.tokens import hash_token, new_token
from app.billing import referrals
from app.billing.config import get_billing_config
from app.config import get_settings
from app.db.models import EmailToken, PendingAuth, Waitlist
from app.db.session import get_db

router = APIRouter(prefix="/api")

EMAIL_TOKEN_TTL = timedelta(minutes=15)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FIFTEEN_MIN = 15 * 60


class EmailIn(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def _valid(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("not an email address")
        return v


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class AuthStep(BaseModel):
    """Where the frontend goes next."""

    next: Literal["signed_in", "invite", "consent", "verify_email", "linked"]


class Accepted(BaseModel):
    status: Literal["ok"] = "ok"


class PendingView(BaseModel):
    kind: Literal["signup", "needs_email"]
    provider: Literal["google", "github", "email"]
    email: str | None
    invite_required: bool
    invite_accepted: bool
    has_bound_invite: bool
    # Invite-only: the rt_ref cookie names someone with invites left, so their link can be the invite.
    has_referral_invite: bool = False


class PublicConfig(BaseModel):
    """Flags the signed-out pages need (the landing page renders from these)."""

    invite_only: bool


class InviteIn(BaseModel):
    code: str | None = Field(default=None, max_length=64)  # None: use the invite bound to the email
    referral: bool = False  # use the friend's referral link (rt_ref cookie) as the invite


class NoticeOut(BaseModel):
    id: uuid.UUID
    purpose: Literal["service", "research", "age_18_plus", "waitlist"]
    version: str
    body_url: str


class CompleteIn(BaseModel):
    age_18_plus: Literal[True]
    accept_terms: Literal[True]
    research_opt_in: bool = False
    notice_ids: dict[Literal["service", "age_18_plus", "research"], uuid.UUID]


class WaitlistIn(EmailIn):
    age_18_plus: Literal[True]
    notice_id: uuid.UUID
    source: str | None = Field(default=None, max_length=100)


def _fail(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail=code)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def after_verified_email() -> Literal["invite", "consent"]:
    """A new, verified identity goes to the invite step, or straight to consent when signup is open."""
    return "invite" if get_settings().invite_only else "consent"


def per_key_limit(key: str, limit: int, window: int) -> None:
    if limiter.hit(key, limit, window) is not None:
        log_auth_event("rate_limited", outcome="denied", reason=key.split(":", 1)[0])
        raise _fail(429, "rate_limited")


async def send_magic_link(db: AsyncSession, email: str, purpose: Literal["login", "verify_pending", "link"],
                     pending_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None) -> None:
    token = new_token()
    db.add(EmailToken(
        token_hash=hash_token(token), email=email, purpose=purpose, pending_id=pending_id, user_id=user_id,
        expires_at=datetime.now(UTC) + EMAIL_TOKEN_TTL,
    ))
    await db.commit()
    get_mailer().send(magic_link_mail(email, token, purpose))
    log_auth_event("magic_link_sent", provider="email", reason=purpose)


async def sign_in_or_gate(
    db: AsyncSession, request: Request, response: Response, *,
    provider: Literal["google", "github", "email"], provider_account_id: str, verified_email: str | None,
) -> AuthStep:
    """Shared ending of every sign-in: existing (or auto-linked) user signs in,
    anyone else becomes a pending identity at the invite (or verify-email) step."""
    try:
        resolved = await resolve_identity(db, provider, provider_account_id, verified_email)
    except AccountUnavailable as exc:
        log_auth_event("account_unavailable", outcome="denied", user_id=exc.user_id, provider=provider)
        raise _fail(403, "account_unavailable") from None
    if resolved.user is not None:
        clear_pending(response)
        await start_session(db, request, response, resolved.user, provider=provider)
        return AuthStep(next="signed_in")
    await create_pending(db, request, response, provider=provider,
                         provider_account_id=provider_account_id, verified_email=verified_email)
    return AuthStep(next=after_verified_email() if verified_email else "verify_email")


# --- magic link ------------------------------------------------------------------------------


@router.post("/auth/email/start", status_code=202,
             dependencies=[Depends(rate_limit("email_start", 5, FIFTEEN_MIN)), Depends(require_csrf)])
async def email_start(body: EmailIn, db: AsyncSession = Depends(get_db)) -> Accepted:
    """Send a sign-in link. Same answer whether or not the address has an account."""
    per_key_limit(f"email_addr:{hashlib.sha256(body.email.encode()).hexdigest()}", 3, FIFTEEN_MIN)
    await send_magic_link(db, body.email, "login")
    return Accepted()


@router.post("/auth/pending/email", status_code=202,
             dependencies=[Depends(rate_limit("email_start", 5, FIFTEEN_MIN)), Depends(require_csrf)])
async def pending_email(body: EmailIn, request: Request, db: AsyncSession = Depends(get_db)) -> Accepted:
    """A provider gave no verified email: confirm one by magic link before going on."""
    pending = await load_pending(db, request)
    if pending is None:
        raise _fail(400, "pending_expired")
    if pending.kind != "needs_email":
        raise _fail(409, "email_already_verified")
    per_key_limit(f"email_addr:{hashlib.sha256(body.email.encode()).hexdigest()}", 3, FIFTEEN_MIN)
    await send_magic_link(db, body.email, "verify_pending", pending.id)
    return Accepted()


@router.post("/auth/email/verify",
             dependencies=[Depends(rate_limit("email_verify", 10, 60)), Depends(require_csrf)])
async def email_verify(body: TokenIn, request: Request, response: Response,
                       db: AsyncSession = Depends(get_db)) -> AuthStep:
    """The page behind a magic link posts its token here. Single use, 15 minutes."""
    # Before touching the token: resolving may commit (session refresh/expiry), and a
    # rejected link must stay unconsumed.
    signed_in = await resolve_session(db, request)
    row = (await db.execute(
        update(EmailToken)
        .where(EmailToken.token_hash == hash_token(body.token), EmailToken.consumed_at.is_(None),
               EmailToken.expires_at > datetime.now(UTC))
        .values(consumed_at=datetime.now(UTC))
        .returning(EmailToken.email, EmailToken.purpose, EmailToken.pending_id, EmailToken.user_id)
    )).one_or_none()
    if row is None:
        await db.rollback()
        raise _fail(400, "link_invalid")
    email, purpose, pending_id, link_user_id = row

    if purpose == "link":
        return await _finish_email_link(db, request, response, signed_in, email, link_user_id)

    if purpose == "login":
        await db.commit()
        log_auth_event("magic_link_used", provider="email", reason="login")
        return await sign_in_or_gate(db, request, response, provider="email",
                                      provider_account_id=email, verified_email=email)

    # verify_pending: must be the same browser that started the sign-in.
    pending = await load_pending(db, request, lock=True)
    if pending is None or pending.id != pending_id:
        await db.rollback()  # leave the link usable in the right browser
        raise _fail(400, "wrong_browser")
    provider, provider_account_id = pending.provider, pending.provider_account_id
    await db.commit()
    log_auth_event("magic_link_used", provider="email", reason="verify_pending")
    try:
        resolved = await resolve_identity(db, provider, provider_account_id, email)
    except AccountUnavailable as exc:
        log_auth_event("account_unavailable", outcome="denied", user_id=exc.user_id, provider=provider)
        raise _fail(403, "account_unavailable") from None
    if resolved.user is not None:
        await db.execute(delete(PendingAuth).where(PendingAuth.id == pending_id))
        clear_pending(response)
        await start_session(db, request, response, resolved.user, provider=provider)
        return AuthStep(next="signed_in")
    await db.execute(update(PendingAuth).where(PendingAuth.id == pending_id)
                     .values(kind="signup", verified_email=email))
    await db.commit()
    return AuthStep(next=after_verified_email())


async def _finish_email_link(db: AsyncSession, request: Request, response: Response,
                             signed_in: SignedIn | None, email: str, user_id: uuid.UUID) -> AuthStep:
    """Add email sign-in for the user who asked, only while they are the one signed in."""
    if signed_in is None or signed_in.user.id != user_id or signed_in.user.status != "active":
        await db.rollback()  # leave the link usable once they sign in to the right account
        raise _fail(400, "wrong_account")
    user = signed_in.user
    await db.commit()
    log_auth_event("magic_link_used", provider="email", reason="link")
    try:
        result = await link(db, user, "email", email, email)
    except AccountError as exc:
        log_auth_event("account_link_failed", outcome="denied", user_id=user.id, provider="email", reason=exc.code)
        raise _fail(409, exc.code) from None
    if result == "linked":
        await start_session(db, request, response, user, provider="email", event="account_linked")
    return AuthStep(next="linked")


# --- invite gate -------------------------------------------------------------------------------


@router.get("/auth/config")
async def public_config() -> PublicConfig:
    return PublicConfig(invite_only=get_settings().invite_only)


@router.get("/auth/pending")
async def get_pending(request: Request, db: AsyncSession = Depends(get_db)) -> PendingView:
    """The sign-in in progress, for the invite / consent / waitlist pages."""
    pending = await load_pending(db, request)
    if pending is None:
        raise _fail(404, "pending_expired")
    bound = bool(pending.verified_email) and await find_bound(db, pending.verified_email) is not None
    return PendingView(kind=pending.kind, provider=pending.provider, email=pending.verified_email,
                       invite_required=get_settings().invite_only,
                       invite_accepted=pending.invite_id is not None or pending.referral_invite,
                       has_bound_invite=bound, has_referral_invite=await _referral_invite(db, request))


async def _referral_invite(db: AsyncSession, request: Request) -> bool:
    config = get_billing_config()
    if not (get_settings().invite_only and config.referrals.enabled):
        return False
    referrer = await referrals.referrer_for(db, request.cookies.get(referrals.COOKIE))
    return referrer is not None and await referrals.invites_left(db, config, referrer.id) > 0


@router.post("/auth/signup/invite",
             dependencies=[Depends(rate_limit("invite", 10, FIFTEEN_MIN)), Depends(require_csrf)])
async def signup_invite(body: InviteIn, request: Request, db: AsyncSession = Depends(get_db)) -> AuthStep:
    """Check an invite (typed, or bound to the verified email) without using it up.
    It is consumed only when the account is created."""
    pending = await load_pending(db, request, lock=True)
    if pending is None:
        raise _fail(400, "pending_expired")
    if pending.kind != "signup" or not pending.verified_email:
        raise _fail(400, "email_unverified")
    per_key_limit(f"invite_pending:{pending.id}", 10, FIFTEEN_MIN)
    email, provider = pending.verified_email, pending.provider  # rollback below expires `pending`
    if body.referral and not body.code:
        if not await _referral_invite(db, request):
            await db.rollback()
            log_auth_event("invite_checked", outcome="denied", provider=provider, reason="referral")
            raise _fail(400, "no_invite")
        pending.referral_invite = True  # used up (and re-checked) only when the account is created
        await db.commit()
        log_auth_event("invite_checked", provider=provider, reason="referral")
        return AuthStep(next="consent")
    invite_id = await (find_usable(db, body.code, email) if body.code else find_bound(db, email))
    if invite_id is None:
        await db.rollback()
        log_auth_event("invite_checked", outcome="denied", provider=provider)
        raise _fail(400, "no_invite")
    pending.invite_id = invite_id
    await db.commit()
    log_auth_event("invite_checked", provider=provider)
    return AuthStep(next="consent")


@router.get("/auth/notices")
async def notices(db: AsyncSession = Depends(get_db)) -> list[NoticeOut]:
    """Current consent notices (service = Terms + Privacy, age_18_plus, research, waitlist)."""
    return [NoticeOut(id=n.id, purpose=n.purpose, version=n.version, body_url=n.body_url)
            for n in (await current_notices(db)).values()]


@router.post("/auth/signup/complete",
             dependencies=[Depends(rate_limit("signup_complete", 5, 60)), Depends(require_csrf)])
async def signup_complete(body: CompleteIn, request: Request, response: Response,
                          db: AsyncSession = Depends(get_db)) -> AuthStep:
    """18+ and Terms are required (validated above); research is optional.
    Creates the account, records consent, and signs in, all at once."""
    pending = await load_pending(db, request, lock=True)
    if pending is None:
        raise _fail(400, "pending_expired")
    provider = pending.provider
    try:
        user = await complete_signup(db, pending, notice_ids=dict(body.notice_ids),
                                     research_opt_in=body.research_opt_in, ip=_ip(request),
                                     referral_code=request.cookies.get(referrals.COOKIE))
    except SignupError as exc:
        await db.rollback()
        log_auth_event("signup_failed", outcome="denied", provider=provider, reason=exc.code)
        status = 409 if exc.code in {"invite_unavailable", "account_exists"} else 400
        raise _fail(status, exc.code) from None
    log_auth_event("signup_completed", user_id=user.id, provider=provider)
    clear_pending(response)
    await start_session(db, request, response, user, provider=provider)
    return AuthStep(next="signed_in")


# --- waitlist ------------------------------------------------------------------------------------


@router.post("/waitlist", status_code=202,
             dependencies=[Depends(rate_limit("waitlist", 5, FIFTEEN_MIN)), Depends(require_csrf)])
async def join_waitlist(body: WaitlistIn, db: AsyncSession = Depends(get_db)) -> Accepted:
    """Same answer for new and already-listed emails, so the form reveals nothing."""
    current = (await current_notices(db)).get("waitlist")
    if current is None or current.id != body.notice_id:
        raise _fail(400, "stale_notice")
    await db.execute(
        insert(Waitlist).values(email=body.email, source=body.source, notice_id=current.id)
        .on_conflict_do_nothing(index_elements=["email"])
    )
    await db.commit()
    log_auth_event("waitlist_joined")
    return Accepted()
