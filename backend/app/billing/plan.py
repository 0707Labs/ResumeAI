"""The user's plan in one line, for the header chip and the dashboard card.

Built on the same snapshot that gates tailoring and downloads (app.billing.analyses), so
what the header says is what the paywall will do. Precedence matches the download order:
an active pass, then Pro, then a credit balance, else the free allowance.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import analyses
from app.billing.config import BillingConfig
from app.db.models import Pass, Subscription, User

Kind = Literal["pass", "pro", "credits", "free"]


@dataclass(frozen=True)
class PlanStatus:
    kind: Kind
    credits: int
    pass_expires_at: datetime | None
    pass_days_left: int | None
    pass_downloads_left: int | None
    pro_period_end: datetime | None
    free_allowance: int
    free_left: int
    resets_at: datetime


async def plan_status(db: AsyncSession, config: BillingConfig, user: User, now: datetime) -> PlanStatus:
    snap = await analyses.snapshot(db, config, user.id, user.credits_balance, now)
    live_pass = next((p for p in snap.passes if p.left > 0), None)
    expires = None
    if live_pass is not None:
        expires = await db.scalar(select(Pass.expires_at).where(Pass.id == live_pass.id))
    pro_end = None
    if snap.pro is not None:
        pro_end = await db.scalar(select(Subscription.current_period_end).where(Subscription.id == snap.pro.id))

    if live_pass is not None:
        kind: Kind = "pass"
    elif snap.pro is not None and snap.pro.left > 0:
        kind = "pro"
    elif snap.credits > 0:
        kind = "credits"
    else:
        kind = "free"
    days_left = None
    if expires is not None:
        days_left = max(0, -(-int((expires - now).total_seconds()) // 86400))  # whole days, rounded up
    return PlanStatus(
        kind=kind, credits=snap.credits, pass_expires_at=expires, pass_days_left=days_left,
        pass_downloads_left=live_pass.left if live_pass else None, pro_period_end=pro_end,
        free_allowance=snap.free_allowance, free_left=max(snap.free_allowance - snap.free_used, 0),
        resets_at=analyses.next_month_start(now),
    )
