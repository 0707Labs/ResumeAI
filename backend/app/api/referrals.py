"""/api/referrals: your referral link, what it earned, and live updates for the header;
/api/admin/referrals: the review queue (approve, reject, reverse). See app.billing.referrals."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.admin import require_admin
from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.billing import referrals
from app.billing.config import BillingConfig, get_billing_config
from app.config import get_settings
from app.db.models import Referral, User
from app.db.session import get_db

router = APIRouter(prefix="/api/referrals")
admin_router = APIRouter(prefix="/api/admin/referrals")

Status = Literal["pending", "rewarded", "rejected"]


class ReferralRow(BaseModel):
    """One friend, without who they are (the referrer never sees the friend's email)."""

    id: uuid.UUID
    status: Status
    reason: str | None
    needs_review: bool
    created_at: datetime
    rewarded_at: datetime | None
    credits: int


class ReferralsOut(BaseModel):
    enabled: bool
    code: str
    link: str
    trigger: Literal["on_verified_signup", "on_first_tailoring"]
    reward_credits: int
    invitee_reward_credits: int
    monthly_cap: int
    rewarded_this_month: int
    invite_only: bool
    invites_left: int
    total_earned: int
    pending: int
    rewarded: int
    referrals: list[ReferralRow]


class Reward(BaseModel):
    id: uuid.UUID
    credits: int
    rewarded_at: datetime


class UpdatesOut(BaseModel):
    """Polled by the header: the live balance and referral rewards not yet shown."""

    credits_balance: int
    new_rewards: list[Reward]


class SeenIn(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=50)


@router.get("")
async def overview(user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
                   config: BillingConfig = Depends(get_billing_config)) -> ReferralsOut:
    code = await referrals.ensure_code(db, user)
    await db.commit()
    rows = list(await db.scalars(select(Referral).where(Referral.referrer_id == user.id)
                                 .order_by(Referral.created_at.desc()).limit(200)))
    month = referrals.month_start(datetime.now(UTC))
    return ReferralsOut(
        enabled=config.referrals.enabled, code=code, link=f"{get_settings().public_url}/?ref={code}",
        trigger=config.referrals.trigger, reward_credits=config.referrals.reward_credits,
        invitee_reward_credits=config.referrals.invitee_reward_credits, monthly_cap=config.referrals.monthly_cap,
        rewarded_this_month=sum(1 for r in rows if r.status == "rewarded" and r.rewarded_at >= month),
        invite_only=get_settings().invite_only, invites_left=await referrals.invites_left(db, config, user.id),
        total_earned=sum(r.reward_credits for r in rows if r.status == "rewarded"),
        pending=sum(1 for r in rows if r.status == "pending"),
        rewarded=sum(1 for r in rows if r.status == "rewarded"),
        referrals=[ReferralRow(id=r.id, status=r.status, reason=r.reason, needs_review=r.needs_review,
                               created_at=r.created_at, rewarded_at=r.rewarded_at,
                               credits=r.reward_credits if r.status == "rewarded" else 0) for r in rows],
    )


@router.get("/updates")
async def updates(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> UpdatesOut:
    rows = await db.scalars(select(Referral).where(
        Referral.referrer_id == user.id, Referral.status == "rewarded", Referral.seen_at.is_(None))
        .order_by(Referral.rewarded_at).limit(20))
    balance = await db.scalar(select(User.credits_balance).where(User.id == user.id))
    return UpdatesOut(credits_balance=balance or 0, new_rewards=[
        Reward(id=r.id, credits=r.reward_credits, rewarded_at=r.rewarded_at) for r in rows])


@router.post("/updates/seen", status_code=204,
             dependencies=[Depends(rate_limit("referral_seen", 30, 60)), Depends(require_csrf)])
async def mark_seen(body: SeenIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> None:
    if body.ids:
        await db.execute(update(Referral).where(Referral.id.in_(body.ids), Referral.referrer_id == user.id,
                                                Referral.seen_at.is_(None)).values(seen_at=func.now()))
        await db.commit()


# --- admin -------------------------------------------------------------------------------------


class AdminReferral(BaseModel):
    id: uuid.UUID
    referrer_email: str | None
    referee_email: str | None
    status: Status
    reason: str | None
    needs_review: bool
    used_as_invite: bool
    same_network: int  # referred sign-ups sharing this network (keyed IP hash)
    reward_credits: int
    created_at: datetime
    rewarded_at: datetime | None
    reversed_at: datetime | None


class DecisionIn(BaseModel):
    reason: str = Field(default="admin", min_length=1, max_length=200)


@admin_router.get("")
async def queue(view: Literal["review", "recent"] = "review", _: User = Depends(require_admin),
                db: AsyncSession = Depends(get_db)) -> list[AdminReferral]:
    referrer, referee = aliased(User), aliased(User)
    q = (select(Referral, referrer.email, referee.email)
         .join(referrer, referrer.id == Referral.referrer_id).join(referee, referee.id == Referral.referee_id))
    q = (q.where(Referral.needs_review, Referral.status == "pending").order_by(Referral.created_at)
         if view == "review" else q.order_by(Referral.created_at.desc())).limit(200)
    out = []
    for row, referrer_email, referee_email in (await db.execute(q)).all():
        cluster = 0 if row.ip_hmac is None else int(await db.scalar(
            select(func.count()).select_from(Referral).where(Referral.ip_hmac == row.ip_hmac)))
        out.append(AdminReferral(
            id=row.id, referrer_email=referrer_email, referee_email=referee_email, status=row.status,
            reason=row.reason, needs_review=row.needs_review, used_as_invite=row.used_as_invite,
            same_network=cluster, reward_credits=row.reward_credits, created_at=row.created_at,
            rewarded_at=row.rewarded_at, reversed_at=row.reversed_at))
    return out


async def _decide(db: AsyncSession, action, *args) -> AdminReferral | None:
    try:
        row = await action(db, *args)
    except referrals.NotAllowed:
        await db.rollback()
        raise HTTPException(status_code=409, detail="not_allowed") from None
    await db.commit()
    return row


@admin_router.post("/{referral_id}/approve", status_code=204, dependencies=[Depends(require_csrf)])
async def approve(referral_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
                  config: BillingConfig = Depends(get_billing_config)) -> None:
    await _decide(db, lambda d: referrals.approve(d, config, referral_id, admin.id))


@admin_router.post("/{referral_id}/reject", status_code=204, dependencies=[Depends(require_csrf)])
async def reject(referral_id: uuid.UUID, body: DecisionIn, admin: User = Depends(require_admin),
                 db: AsyncSession = Depends(get_db)) -> None:
    await _decide(db, lambda d: referrals.reject(d, referral_id, admin.id, body.reason))


@admin_router.post("/{referral_id}/reverse", status_code=204, dependencies=[Depends(require_csrf)])
async def reverse(referral_id: uuid.UUID, body: DecisionIn, admin: User = Depends(require_admin),
                  db: AsyncSession = Depends(get_db)) -> None:
    await _decide(db, lambda d: referrals.reverse(d, referral_id, admin.id, body.reason))
