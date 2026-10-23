"""Analyses (tailoring runs) and downloads: tailoring is free to try, the download pays.

start_analysis() pins a resume and job description on the server. It spends nothing:
the monthly free tailorings allow it, or, past those, whatever a download would need (an
active pass, Pro, or a credit balance; see app.billing.entitlements). It may use Claude
only while the user is under the daily Claude cap; past it the analysis starts
rules-only. pay_for_download()
runs when the user asks for the clean DOCX/PDF of an analysis: a paid download of the
same analysis within redownload_free_days covers it ('window'); otherwise it is charged
to a pass, Pro or credits (can_user_run), once, through the ledger.

Every function runs inside the caller's transaction and never commits. The download
route checks the file renders inside the same transaction, so a failed export charges
nothing. Each function first locks the user's row (the same lock app.billing.ledger
takes), so one user's starts and downloads are serialized: concurrent clicks can't
overspend credits, the free tailorings, a fair-use cap or the daily Claude cap, and
can't pay twice for one analysis within the window.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import ledger
from app.billing.config import BillingConfig
from app.billing.entitlements import CapUsage, Decision, Snapshot, can_start_tailoring, can_user_run
from app.db.models import Analysis, Download, Pass, Subscription, User

log = logging.getLogger("app.billing")

# Analyses that may use Claude. One started over the daily cap is usable until the moment
# it was created, so app.api.analyses never lets Claude run for it.
WITH_CLAUDE = Analysis.usable_until > Analysis.created_at
# Runs that use up a free tailoring: all but those that ended (or started) rules-only.
COUNTS = and_(WITH_CLAUDE, or_(Analysis.llm_tailored.is_(None), Analysis.llm_tailored.is_(True)))
PAID = Download.paid_with != "window"  # downloads that were charged to something


class NoEntitlement(Exception):
    def __init__(self, decision: Decision):
        super().__init__(decision.reason)
        self.decision = decision


class UnknownAnalysis(Exception):
    """Not this user's analysis (or no such analysis)."""


class AnalysisPurged(Exception):
    """The retention purge has cleared this analysis's resume text (app.billing.retention):
    it can't be downloaded again; the user tailors again instead."""


@dataclass(frozen=True)
class Started:
    analysis: Analysis
    decision: Decision | None  # None for a replayed idempotency key
    replay: bool
    claude_per_day: int  # the daily Claude cap that applies to this user now

    @property
    def claude(self) -> bool:
        """False when the analysis was started over the daily Claude cap (rules-only)."""
        return self.analysis.usable_until > self.analysis.created_at


@dataclass(frozen=True)
class Paid:
    download: Download
    decision: Decision | None  # None when the re-download window covered it


def inputs_digest(resume: dict, jd: dict) -> str:
    """sha256 of the parsed resume and job description, as JSON with sorted keys."""
    blob = json.dumps({"resume": resume, "jd": jd}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def day_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month_start(now: datetime) -> datetime:
    start = month_start(now)
    return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)


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


async def _paid_downloads(db: AsyncSession, *where) -> int:
    return int(await db.scalar(select(func.count()).select_from(Download).where(PAID, *where)))


async def snapshot(db: AsyncSession, config: BillingConfig, user_id: uuid.UUID, balance: int,
                   now: datetime) -> Snapshot:
    """What this user has now. Fair-use caps count paid downloads; the free allowance
    counts tailorings started this calendar month."""
    passes = []
    for p in await db.scalars(select(Pass).where(
            Pass.user_id == user_id, Pass.revoked_at.is_(None), Pass.starts_at <= now, Pass.expires_at > now)
            .order_by(Pass.starts_at, Pass.id)):
        passes.append(CapUsage(p.id, await _paid_downloads(db, Download.pass_id == p.id), p.analyses_cap))

    pro = None
    sub = await db.scalar(select(Subscription).where(
        Subscription.user_id == user_id, Subscription.status == "active").order_by(Subscription.updated_at.desc()))
    product = config.products.get(sub.product_key) if sub is not None else None
    if sub is not None and product is not None and product.fair_use_cap is not None and (
            sub.current_period_end is None or sub.current_period_end > now):
        # Someone who paid keeps Pro even if the product's sale flag is later turned off.
        start = (_minus_interval(sub.current_period_end, product.interval) if sub.current_period_end
                 else now - timedelta(days=31))
        used = await _paid_downloads(db, Download.subscription_id == sub.id, Download.created_at > start)
        pro = CapUsage(sub.id, used, product.fair_use_cap)

    free_used = int(await db.scalar(select(func.count()).select_from(Analysis).where(
        Analysis.user_id == user_id, COUNTS, Analysis.created_at >= month_start(now))))
    return Snapshot(credits=balance, passes=tuple(passes), pro=pro, free_used=free_used,
                    free_allowance=config.free.analyses_per_month,
                    credits_per_download=config.downloads.credits_per_download)


def _label(value: object) -> str | None:
    """A job title or company for lists: one line, at most 200 characters."""
    text = " ".join(str(value).split()) if value else ""
    return text[:200] or None


async def start_analysis(db: AsyncSession, config: BillingConfig, user_id: uuid.UUID, *, resume: dict, jd: dict,
                         idempotency_key: str, now: datetime | None = None) -> Started:
    """Pin a resume and job description for this user. Spends nothing; raises
    NoEntitlement past the free tailorings without a pass, Pro or credits. The same
    key returns the same analysis. Claude may be used for it while the user has started
    fewer than the daily cap of Claude analyses since 00:00 UTC (the paid cap with an
    active pass or Pro); past the cap it starts rules-only (Started.claude is False) and
    uses up no free tailoring."""
    now = now or datetime.now(UTC)
    balance = await _lock_user(db, user_id)
    snap = await snapshot(db, config, user_id, balance, now)
    cap = (config.analyses.paid_claude_analyses_per_day if snap.passes or snap.pro is not None
           else config.analyses.claude_analyses_per_day)
    existing = await db.scalar(select(Analysis).where(
        Analysis.user_id == user_id, Analysis.idempotency_key == idempotency_key))
    if existing is not None:
        return Started(existing, None, replay=True, claude_per_day=cap)
    decision = can_start_tailoring(snap)
    if not decision.allowed:
        raise NoEntitlement(decision)
    used = int(await db.scalar(select(func.count()).select_from(Analysis).where(
        Analysis.user_id == user_id, Analysis.created_at >= day_start(now), WITH_CLAUDE)))
    usable_until = now + timedelta(hours=config.analyses.usable_hours) if used < cap else now
    row = Analysis(id=uuid.uuid4(), user_id=user_id, idempotency_key=idempotency_key, resume=resume, jd=jd,
                   inputs_sha256=inputs_digest(resume, jd), created_at=now, usable_until=usable_until,
                   job_title=_label(jd.get("title")), company=_label(jd.get("company")),
                   entitlement=decision.pays_with)
    db.add(row)
    await db.flush()
    return Started(row, decision, replay=False, claude_per_day=cap)


async def usable(db: AsyncSession, user_id: uuid.UUID, analysis_id: uuid.UUID,
                 now: datetime | None = None) -> Analysis | None:
    """The user's analysis while Claude may still be used for it; anyone else's id, an
    unknown one or an expired one gives None."""
    now = now or datetime.now(UTC)
    return await db.scalar(select(Analysis).where(
        Analysis.id == analysis_id, Analysis.user_id == user_id, Analysis.usable_until > now,
        Analysis.purged_at.is_(None)))


async def owned(db: AsyncSession, user_id: uuid.UUID, analysis_id: uuid.UUID, *, lock: bool = False) -> Analysis:
    """The user's analysis, with its text. UnknownAnalysis for anyone else's or an unknown
    id; AnalysisPurged once the retention purge has cleared it. lock=True holds the row
    (and re-reads it), so a purge running now skips it."""
    query = select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None:
        raise UnknownAnalysis(analysis_id)
    if row.purged_at is not None:
        raise AnalysisPurged(analysis_id)
    return row


async def pay_for_download(db: AsyncSession, config: BillingConfig, user_id: uuid.UUID, analysis_id: uuid.UUID,
                           *, fmt: str, final_resume: dict, now: datetime | None = None) -> Paid:
    """Record a download of this analysis and pay for it: free within the re-download
    window of a paid download of the same analysis, else charged to a pass, Pro or
    credits (key download:{id}). Raises NoEntitlement when nothing pays,
    UnknownAnalysis for someone else's analysis and AnalysisPurged for a purged one."""
    now = now or datetime.now(UTC)
    balance = await _lock_user(db, user_id)
    await owned(db, user_id, analysis_id, lock=True)
    window = timedelta(days=config.downloads.redownload_free_days)
    last_paid = await db.scalar(select(func.max(Download.created_at)).where(
        Download.analysis_id == analysis_id, Download.user_id == user_id, PAID))
    decision = None
    row = Download(id=uuid.uuid4(), user_id=user_id, analysis_id=analysis_id, format=fmt,
                   final_resume=final_resume, created_at=now)
    if last_paid is not None and now - last_paid < window:
        row.paid_with = "window"
    else:
        decision = can_user_run(await snapshot(db, config, user_id, balance, now))
        if not decision.allowed:
            raise NoEntitlement(decision)
        row.paid_with, row.pass_id, row.subscription_id = decision.pays_with, decision.pass_id, decision.subscription_id
        row.credits = config.downloads.credits_per_download if decision.pays_with == "credit" else 0
    db.add(row)
    await db.flush()
    if row.paid_with == "credit":
        await ledger.charge(db, user_id, row.credits, reason="analysis_charge",
                            idempotency_key=f"download:{row.id}", reference_id=str(row.id))
    # The download log: ids and what paid, never resume text.
    log.info("download user=%s analysis=%s download=%s format=%s paid_with=%s credits=%d",
             user_id, analysis_id, row.id, fmt, row.paid_with, row.credits)
    return Paid(row, decision)
