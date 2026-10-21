"""Analyses as the unit of billing.

Tailoring is free; the download pays. start_analysis() pins a resume and job
description on the server (free). pay_for_download() runs on the first DOCX/PDF export
of an analysis: it picks what pays (a pass, Pro, a credit or a free download, see
app.billing.entitlements) and charges it once; later exports of that analysis are free.

Every function runs inside the caller's transaction and never commits. The export
route renders the file inside the same transaction, so a failed export charges
nothing. Each function first locks the user's row (the same lock app.billing.ledger
takes), so one user's payments are serialized: concurrent downloads can't overspend
credits, the free downloads or a fair-use cap, and can't pay twice for one analysis.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import ledger
from app.billing.config import BillingConfig
from app.billing.entitlements import CapUsage, Decision, Snapshot, can_user_run
from app.db.models import Analysis, Pass, Subscription, User

PAID = Analysis.paid_at.is_not(None)  # analyses that used up an allowance or a cap


class NoEntitlement(Exception):
    def __init__(self, decision: Decision):
        super().__init__(decision.reason)
        self.decision = decision


class UnknownAnalysis(Exception):
    """Not this user's analysis (or no such analysis)."""


@dataclass(frozen=True)
class Started:
    analysis: Analysis
    replay: bool


@dataclass(frozen=True)
class Payment:
    analysis: Analysis
    decision: Decision | None  # None when the analysis was already paid for (a re-export)


def inputs_digest(resume: dict, jd: dict) -> str:
    """sha256 of the parsed resume and job description, as JSON with sorted keys."""
    blob = json.dumps({"resume": resume, "jd": jd}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


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
    return int(await db.scalar(select(func.count()).select_from(Analysis).where(PAID, *where)))


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
        used = await _count(db, Analysis.subscription_id == sub.id, Analysis.paid_at > start)
        pro = CapUsage(sub.id, used, product.fair_use_cap)

    free_used = await _count(db, Analysis.user_id == user_id, Analysis.entitlement == "free",
                             Analysis.paid_at >= _month_start(now))
    return Snapshot(credits=balance, passes=tuple(passes), pro=pro, free_used=free_used,
                    free_allowance=config.free.analyses_per_month,
                    credits_per_analysis=config.analyses.credits_per_analysis)


async def start_analysis(db: AsyncSession, config: BillingConfig, user_id: uuid.UUID, *, resume: dict, jd: dict,
                         idempotency_key: str, now: datetime | None = None) -> Started:
    """Pin a resume and job description for this user. Free; the same key returns the
    same analysis."""
    now = now or datetime.now(UTC)
    await _lock_user(db, user_id)
    existing = await db.scalar(select(Analysis).where(
        Analysis.user_id == user_id, Analysis.idempotency_key == idempotency_key))
    if existing is not None:
        return Started(existing, replay=True)
    row = Analysis(id=uuid.uuid4(), user_id=user_id, idempotency_key=idempotency_key, resume=resume, jd=jd,
                   inputs_sha256=inputs_digest(resume, jd), created_at=now,
                   usable_until=now + timedelta(hours=config.analyses.usable_hours))
    db.add(row)
    await db.flush()
    return Started(row, replay=False)


async def usable(db: AsyncSession, user_id: uuid.UUID, analysis_id: uuid.UUID,
                 now: datetime | None = None) -> Analysis | None:
    """The user's analysis while Claude may still be used for it; anyone else's id, an
    unknown one or an expired one gives None."""
    now = now or datetime.now(UTC)
    return await db.scalar(select(Analysis).where(
        Analysis.id == analysis_id, Analysis.user_id == user_id, Analysis.usable_until > now))


async def pay_for_download(db: AsyncSession, config: BillingConfig, user_id: uuid.UUID,
                           analysis_id: uuid.UUID, *, now: datetime | None = None) -> Payment:
    """Charge the first download of an analysis, once. A credit is spent through the
    ledger with key charge:{analysis_id}. Raises NoEntitlement when nothing pays and
    UnknownAnalysis for someone else's analysis."""
    now = now or datetime.now(UTC)
    balance = await _lock_user(db, user_id)
    row = await db.scalar(select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user_id)
                          .with_for_update())
    if row is None:
        raise UnknownAnalysis(analysis_id)
    if row.paid_at is not None:
        return Payment(row, None)
    decision = can_user_run(await snapshot(db, config, user_id, balance, now))
    if not decision.allowed:
        raise NoEntitlement(decision)
    row.entitlement, row.paid_at, row.credits = decision.pays_with, now, decision.credits
    row.pass_id, row.subscription_id = decision.pass_id, decision.subscription_id
    await db.flush()
    if decision.pays_with == "credit":
        await ledger.charge(db, user_id, decision.credits, reason="analysis_charge",
                            idempotency_key=f"charge:{row.id}", reference_id=str(row.id))
    return Payment(row, decision)
