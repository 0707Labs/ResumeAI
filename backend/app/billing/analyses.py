"""Analyses as the unit of billing: start (decide who pays, reserve a credit), finish
(commit the credit), release (refund it once), and the sweep for abandoned runs.

Every function runs inside the caller's transaction and never commits. Each one locks
the user's row first (the same lock app.billing.ledger takes), so for one user, starts,
commits and refunds are serialized and always take locks in the order user, then analysis:
- concurrent starts can't overspend credits, the free allowance or a fair-use cap;
- an analysis is settled once: the conditional UPDATE ... WHERE status = 'pending' lets only
  one of a racing finish, failure or sweep through, and the refund:{id} ledger key (plus a
  unique index on refunds per analysis) backs that up.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import ledger
from app.billing.config import BillingConfig
from app.billing.entitlements import CapUsage, Decision, Snapshot, can_user_run
from app.db.models import Analysis, Pass, Subscription, User

log = logging.getLogger("app.billing")

COUNTS = Analysis.status != "failed"  # runs that use up an allowance or a cap


class NoEntitlement(Exception):
    def __init__(self, decision: Decision):
        super().__init__(decision.reason)
        self.decision = decision


@dataclass(frozen=True)
class Started:
    analysis: Analysis
    decision: Decision | None  # None for a replayed idempotency key
    replay: bool


def _month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _minus_interval(end: datetime, interval: str | None) -> datetime:
    """One billing period before end, clamping the day (31 March -> 28/29 February)."""
    year, month = (end.year - 1, end.month) if interval == "year" else (
        (end.year, end.month - 1) if end.month > 1 else (end.year - 1, 12))
    for day in range(end.day, 27, -1):
        try:
            return end.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    return end.replace(year=year, month=month, day=28)


async def _lock_user(db: AsyncSession, user_id: uuid.UUID) -> int:
    balance = await db.scalar(select(User.credits_balance).where(User.id == user_id).with_for_update())
    if balance is None:
        raise ledger.LedgerError("unknown user")
    return balance


async def _count(db: AsyncSession, *where) -> int:
    return int(await db.scalar(select(func.count()).select_from(Analysis).where(COUNTS, *where)))


async def snapshot(db: AsyncSession, config: BillingConfig, user_id: uuid.UUID, balance: int,
                   now: datetime) -> Snapshot:
    passes = []
    for p in await db.scalars(select(Pass).where(
            Pass.user_id == user_id, Pass.revoked_at.is_(None), Pass.starts_at <= now, Pass.expires_at > now)
            .order_by(Pass.starts_at, Pass.id)):
        passes.append(CapUsage(p.id, await _count(db, Analysis.pass_id == p.id), p.analyses_cap))

    pro = None
    sub = await db.scalar(select(Subscription).where(
        Subscription.user_id == user_id, Subscription.status == "active").order_by(Subscription.updated_at.desc()))
    product = config.products.get(sub.product_key) if sub is not None else None
    if sub is not None and product is not None and product.fair_use_cap is not None and (
            sub.current_period_end is None or sub.current_period_end > now):
        # Someone who paid keeps Pro even if the product's sale flag is later turned off.
        start = (_minus_interval(sub.current_period_end, product.interval) if sub.current_period_end
                 else now - timedelta(days=31))
        used = await _count(db, Analysis.subscription_id == sub.id, Analysis.created_at > start)
        pro = CapUsage(sub.id, used, product.fair_use_cap)

    free_used = await _count(db, Analysis.user_id == user_id, Analysis.entitlement == "free",
                             Analysis.created_at >= _month_start(now))
    return Snapshot(credits=balance, passes=tuple(passes), pro=pro, free_used=free_used,
                    free_allowance=config.free.analyses_per_month,
                    credits_per_analysis=config.analyses.credits_per_analysis)


async def start_analysis(db: AsyncSession, config: BillingConfig, user_id: uuid.UUID, *,
                         idempotency_key: str, now: datetime | None = None) -> Started:
    """Decide what pays and, for a credit, charge it ('reserved'). The same key returns
    the same analysis without charging again. Raises NoEntitlement when nothing pays."""
    now = now or datetime.now(UTC)
    balance = await _lock_user(db, user_id)
    if await _sweep_user(db, user_id, now):
        balance = await _lock_user(db, user_id)
    existing = await db.scalar(select(Analysis).where(
        Analysis.user_id == user_id, Analysis.idempotency_key == idempotency_key))
    if existing is not None:
        return Started(existing, None, replay=True)

    decision = can_user_run(await snapshot(db, config, user_id, balance, now))
    if not decision.allowed:
        raise NoEntitlement(decision)
    row = Analysis(
        id=uuid.uuid4(), user_id=user_id, idempotency_key=idempotency_key, status="pending",
        entitlement=decision.pays_with, billing_state="reserved" if decision.pays_with == "credit" else "none",
        credits=decision.credits, pass_id=decision.pass_id, subscription_id=decision.subscription_id,
        usable_until=now + timedelta(hours=config.analyses.usable_hours), created_at=now,
    )
    db.add(row)
    await db.flush()
    if decision.pays_with == "credit":
        await ledger.charge(db, user_id, decision.credits, reason="analysis_charge",
                            idempotency_key=f"charge:{row.id}", reference_id=str(row.id))
    return Started(row, decision, replay=False)


async def usable(db: AsyncSession, user_id: uuid.UUID, analysis_id: uuid.UUID,
                 now: datetime | None = None) -> Analysis | None:
    """The user's analysis if Claude may still be used for it (not failed, not past
    usable_until). Anyone else's id, or an unknown one, gives None."""
    now = now or datetime.now(UTC)
    return await db.scalar(select(Analysis).where(
        Analysis.id == analysis_id, Analysis.user_id == user_id, Analysis.status != "failed",
        Analysis.usable_until > now))


async def finish(db: AsyncSession, analysis_id: uuid.UUID, user_id: uuid.UUID, *,
                 now: datetime | None = None) -> bool:
    """Tailoring succeeded with Claude: commit the credit. True only the first time;
    False also for a run already refunded (late success keeps its result, no new charge)."""
    await _lock_user(db, user_id)
    result = await db.execute(
        update(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user_id, Analysis.status == "pending")
        .values(status="succeeded", finished_at=now or func.now(),
                billing_state=case((Analysis.billing_state == "reserved", "committed"), else_=Analysis.billing_state))
    )
    if result.rowcount != 1:
        log.info("analysis %s was already settled; nothing committed", analysis_id)
    return result.rowcount == 1


async def release(db: AsyncSession, analysis_id: uuid.UUID, user_id: uuid.UUID | None, *, reason: str,
                  degraded: bool = False, now: datetime | None = None) -> bool:
    """Mark a pending analysis failed and refund its credit, exactly once.
    reason: 'llm_degraded' (fell back to rules only), 'error', 'abandoned'."""
    if user_id is not None:
        await _lock_user(db, user_id)
    settled = (await db.execute(
        update(Analysis).where(Analysis.id == analysis_id, Analysis.status == "pending")
        .values(status="failed", failure_reason=reason, llm_degraded=degraded, finished_at=now or func.now(),
                billing_state=case((Analysis.billing_state == "reserved", "refunded"), else_=Analysis.billing_state))
        .returning(Analysis.billing_state, Analysis.credits, Analysis.user_id)
    )).one_or_none()
    if settled is None:
        return False
    state, credits, owner = settled
    if state == "refunded" and owner is not None:
        await ledger.grant(db, owner, credits, reason="refund", idempotency_key=f"refund:{analysis_id}",
                           reference_id=str(analysis_id), note=reason)
    return True


async def _sweep_user(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> int:
    """Release this user's runs left pending past usable_until (caller holds the user lock)."""
    stale = list(await db.scalars(select(Analysis.id).where(
        Analysis.user_id == user_id, Analysis.status == "pending", Analysis.usable_until <= now)))
    for analysis_id in stale:
        await release(db, analysis_id, user_id, reason="abandoned", now=now)
    return len(stale)


async def sweep(db: AsyncSession, *, now: datetime | None = None, limit: int = 500) -> int:
    """Release every abandoned run (for cron). Runs are also swept per user on their next
    start, so a missed cron run only delays a refund."""
    now = now or datetime.now(UTC)
    stale = (await db.execute(select(Analysis.id, Analysis.user_id).where(
        Analysis.status == "pending", Analysis.usable_until <= now)
        .order_by(Analysis.user_id, Analysis.id).limit(limit))).all()
    released = 0
    for analysis_id, user_id in stale:
        released += await release(db, analysis_id, user_id, reason="abandoned", now=now)
    return released
