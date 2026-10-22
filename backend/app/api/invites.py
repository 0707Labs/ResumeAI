"""/api/invites: invite friends by email, within a hard per-user quota.

The quota ([referrals].invites_per_user, default 10) covers email invites and sign-ups
through the user's referral link. It's enforced in Postgres (create_user_invite /
revoke_user_invite / take_invite_slot, migration 0013): each locks the user's row, so
concurrent requests can't create an 11th invite. Revoking an invite nobody used gives the
slot back. An email invite is bound to that address (no code to type) and lasts 30 days;
the friend who sends it becomes the referrer, so the referral reward follows.

Listing reads invites, redemptions and the friends' referral progress, which aren't
the caller's own rows, so it runs as the service role with explicit filters on the caller.
Friends' addresses are always masked.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import exists, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.signin import EmailIn, per_key_limit
from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.invites import generate_code, hash_code
from app.auth.mailer import MailerError, get_mailer, invite_mail
from app.auth.ratelimit import rate_limit
from app.billing import referrals
from app.billing.config import BillingConfig, get_billing_config
from app.config import get_settings
from app.db.models import Analysis, Invite, InviteRedemption, Referral, User
from app.db.rls import service_scope
from app.db.session import get_db

log = logging.getLogger("app.invites")
router = APIRouter(prefix="/api/invites")
INVITE_DAYS = 30

Status = Literal["sent", "expired", "revoked", "joined", "first_tailoring", "rewarded", "not_eligible"]


def mask(email: str | None) -> str:
    """a***@example.com: enough to recognise your own friend, not to harvest addresses."""
    if not email or "@" not in email:
        return "someone"
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


class Invitee(BaseModel):
    id: uuid.UUID  # the invite (email invites) or the referral (link sign-ups)
    via: Literal["email", "link"]
    email: str  # masked
    status: Status
    created_at: datetime
    expires_at: datetime | None
    can_revoke: bool


class InvitesOut(BaseModel):
    limit: int
    used: int
    left: int
    enabled: bool  # referral rewards on
    code: str
    link: str
    trigger: Literal["on_verified_signup", "on_first_tailoring"]
    reward_credits: int
    credits_earned: int
    invitees: list[Invitee]


async def _progress(db: AsyncSession, referee_id: uuid.UUID, referral: Referral | None) -> Status:
    if referral is not None and referral.status == "rewarded":
        return "rewarded"
    if referral is not None and referral.status == "rejected":
        return "not_eligible"
    tailored = await db.scalar(select(exists().where(Analysis.user_id == referee_id, Analysis.tailored_at.is_not(None))))
    return "first_tailoring" if tailored else "joined"


@router.get("")
async def overview(user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
                   config: BillingConfig = Depends(get_billing_config)) -> InvitesOut:
    code = await referrals.ensure_code(db, user)
    await db.commit()
    uid, now = user.id, datetime.now(UTC)
    async with service_scope(db):
        used = int(await db.scalar(select(User.invites_created).where(User.id == uid)) or 0)
        mine = {r.referee_id: r for r in await db.scalars(select(Referral).where(Referral.referrer_id == uid))}
        invites = list(await db.scalars(select(Invite).where(Invite.created_by == uid, Invite.kind == "personal")
                                        .order_by(Invite.created_at.desc()).limit(100)))
        redeemed = {i: u for i, u in (await db.execute(select(InviteRedemption.invite_id, InviteRedemption.user_id)
                                                        .where(InviteRedemption.invite_id.in_([i.id for i in invites])))).all()}
        out: list[Invitee] = []
        for inv in invites:
            friend = redeemed.get(inv.id)
            if friend is not None:
                status: Status = await _progress(db, friend, mine.pop(friend, None))
            elif inv.revoked_at is not None:
                status = "revoked"
            elif inv.expires_at is not None and inv.expires_at <= now:
                status = "expired"
            else:
                status = "sent"
            out.append(Invitee(id=inv.id, via="email", email=mask(inv.email), status=status, created_at=inv.created_at,
                               expires_at=inv.expires_at, can_revoke=status == "sent"))
        emails = dict((await db.execute(select(User.id, User.email).where(User.id.in_(list(mine))))).all())
        for referee, ref in mine.items():  # sign-ups through the link
            out.append(Invitee(id=ref.id, via="link", email=mask(emails.get(referee)),
                               status=await _progress(db, referee, ref), created_at=ref.created_at,
                               expires_at=None, can_revoke=False))
        earned = sum(r.reward_credits for r in await db.scalars(
            select(Referral).where(Referral.referrer_id == uid, Referral.status == "rewarded")))
    out.sort(key=lambda i: i.created_at, reverse=True)
    limit = config.referrals.invites_per_user
    return InvitesOut(limit=limit, used=used, left=max(limit - used, 0), enabled=config.referrals.enabled,
                      code=code, link=f"{get_settings().public_url}/?ref={code}", trigger=config.referrals.trigger,
                      reward_credits=config.referrals.reward_credits, credits_earned=earned, invitees=out)


class Sent(BaseModel):
    id: uuid.UUID
    email: str  # masked
    expires_at: datetime
    left: int


@router.post("", status_code=201, dependencies=[Depends(rate_limit("invite_send", 10, 3600)), Depends(require_csrf)])
async def send_invite(body: EmailIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
                      config: BillingConfig = Depends(get_billing_config)) -> Sent:
    """Invite a friend by email. 409 invite_limit past the quota, already_member when the
    address has an account, already_invited when your invite to it is still open."""
    per_key_limit(f"invite_user:{user.id}", 5, 3600)
    email, uid, name = body.email, user.id, user.name
    if referrals.same_person_key(email) == referrals.same_person_key(user.email):
        raise HTTPException(status_code=422, detail="own_email")
    if referrals.is_disposable(email, config):
        raise HTTPException(status_code=422, detail="disposable_email")
    now = datetime.now(UTC)
    async with service_scope(db):
        # Says whether the address has an account. Bounded by the rate limits above, and
        # needed so a slot isn't spent on someone who can already sign in.
        if await db.scalar(select(exists().where(User.email == email, User.deleted_at.is_(None)))):
            raise HTTPException(status_code=409, detail="already_member")
        if await db.scalar(select(exists().where(
                Invite.created_by == uid, Invite.kind == "personal", Invite.email == email, Invite.uses == 0,
                Invite.revoked_at.is_(None), Invite.expires_at > now))):
            raise HTTPException(status_code=409, detail="already_invited")
    code, expires = generate_code(), now + timedelta(days=INVITE_DAYS)
    try:
        invite_id = await db.scalar(text("SELECT create_user_invite(:u, :n, :h, :hint, :e, :x)"), {
            "u": uid, "n": config.referrals.invites_per_user, "h": hash_code(code), "hint": code[-4:],
            "e": email, "x": expires})
    except DBAPIError as exc:
        await db.rollback()
        if "invite_limit" in str(exc.orig):
            raise HTTPException(status_code=409, detail="invite_limit") from None
        raise
    try:  # before the commit: no invite (and no slot used) if the email can't go out
        await run_in_threadpool(get_mailer().send, invite_mail(email, name, f"{expires:%-d %B %Y}"))
    except MailerError as exc:
        await db.rollback()
        log.warning("invite email failed: %s", exc.reason)
        raise HTTPException(status_code=503, detail="email_unavailable") from None
    await db.commit()
    left = await referrals.invites_left(db, config, uid)
    return Sent(id=invite_id, email=mask(email), expires_at=expires, left=left)


@router.delete("/{invite_id}", status_code=204,
               dependencies=[Depends(rate_limit("invite_revoke", 20, 60)), Depends(require_csrf)])
async def revoke(invite_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> None:
    """Revoke an invite nobody has used yet; its slot comes back."""
    uid = user.id
    async with service_scope(db):
        row = await db.scalar(select(Invite).where(Invite.id == invite_id, Invite.created_by == uid,
                                                   Invite.kind == "personal"))
    if row is None or row.revoked_at is not None:
        raise HTTPException(status_code=404, detail="not_found")
    if row.uses > 0:
        raise HTTPException(status_code=409, detail="already_used")
    if not await db.scalar(text("SELECT revoke_user_invite(:u, :i)"), {"u": uid, "i": invite_id}):
        raise HTTPException(status_code=404, detail="not_found")
    await db.commit()
