"""/api/admin: overview, integrations, webhook log, quality, and the config view. Plus
the public landing-view counter (POST /api/metrics/landing-view).

Overview needs staff.access; its revenue and cost figures are left out (null) for a
role without billing.read / costs.read. Integrations need integrations.read (secret
hints: secrets.hint); a webhook replay needs billing.write; quality needs quality.read;
the config view needs audit.read. Responses are metadata and counts, never resume or job
description text, never secret values.
"""

import csv
import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import Date, case, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import audit, counters
from app.admin import integrations as integ
from app.admin import settings as runtime
from app.api.admin import READ_LIMIT, WRITE, Reason
from app.api.billing import billing_config, payment_provider
from app.auth.ratelimit import rate_limit
from app.auth.roles import can, require
from app.billing import webhooks
from app.billing.admin import PAID_EVER
from app.billing.config import BillingConfig
from app.billing.providers import PaymentProvider
from app.db.models import (
    AggregateRun,
    Analysis,
    AuthSession,
    ConsentNotice,
    CreditTransaction,
    DailyCounter,
    DailyLlmCost,
    DailyRevenue,
    Download,
    IntegrationCheck,
    Payment,
    ProcessedWebhookEvent,
    Subscription,
    SupportTicket,
    User,
    Waitlist,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/admin")
public_router = APIRouter(prefix="/api/metrics")
Days = Query(30, ge=1, le=365)


def _first(days: int, now: datetime) -> date:
    return (now - timedelta(days=days - 1)).date()


def _start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _utc_day(column):
    return cast(func.timezone("UTC", column), Date)


async def _count(db: AsyncSession, stmt) -> int:
    return int(await db.scalar(stmt) or 0)


# --- landing views (public) ---------------------------------------------------------------------


@public_router.post("/landing-view", status_code=204, dependencies=[Depends(rate_limit("landing_view", 30, 60))])
async def landing_view() -> None:
    """One landing page view, for the funnel. No cookie, no IP stored, no user: a daily count."""
    counters.bump("landing.view")


# --- overview -----------------------------------------------------------------------------------


async def _series(db: AsyncSession, first: date, days: int, money: bool, costs: bool) -> list[dict[str, Any]]:
    out = {(first + timedelta(days=i)).isoformat(): {"day": (first + timedelta(days=i)).isoformat(), "signups": 0,
                                                     "revenue_usd": 0.0 if money else None,
                                                     "cost_usd": 0.0 if costs else None} for i in range(days)}
    day = _utc_day(User.created_at)
    for d, n in (await db.execute(select(day, func.count()).where(User.created_at >= _start(first)).group_by(day))).all():
        if d.isoformat() in out:
            out[d.isoformat()]["signups"] = int(n)
    if money:
        net = func.sum(DailyRevenue.settled_usd_cents - DailyRevenue.refunded_usd_cents)
        for d, cents in (await db.execute(select(DailyRevenue.day, net).where(DailyRevenue.day >= first)
                                          .group_by(DailyRevenue.day))).all():
            out[d.isoformat()]["revenue_usd"] = round(int(cents or 0) / 100, 2)
    if costs:
        for d, usd in (await db.execute(select(DailyLlmCost.day, func.sum(DailyLlmCost.cost_usd))
                                        .where(DailyLlmCost.day >= first).group_by(DailyLlmCost.day))).all():
            out[d.isoformat()]["cost_usd"] = round(float(usd or 0), 4)
    return list(out.values())


async def overview_data(db: AsyncSession, config: BillingConfig, viewer: User, days: int,
                        now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    first = _first(days, now)
    since = _start(first)
    money, costs = can(viewer.role, "billing.read"), can(viewer.role, "costs.read")
    live = User.deleted_at.is_(None)

    async def active(delta: timedelta) -> int:
        return await _count(db, select(func.count(func.distinct(AuthSession.user_id)))
                            .where(AuthSession.last_seen_at >= now - delta))

    paid_user = exists().where(Payment.user_id == User.id, Payment.status.in_(PAID_EVER))
    users = {
        "total": await _count(db, select(func.count()).select_from(User).where(live)),
        "new_7d": await _count(db, select(func.count()).select_from(User).where(User.created_at >= now - timedelta(days=7))),
        "new_30d": await _count(db, select(func.count()).select_from(User).where(User.created_at >= now - timedelta(days=30))),
        "dau": await active(timedelta(days=1)), "wau": await active(timedelta(days=7)), "mau": await active(timedelta(days=30)),
        "waitlist": await _count(db, select(func.count()).select_from(Waitlist).where(Waitlist.status == "waiting")),
        "paid": await _count(db, select(func.count()).select_from(User).where(live, paid_user)),
    }
    tailored = Analysis.tailored_at.is_not(None)
    tailorings = {
        "d7": await _count(db, select(func.count()).select_from(Analysis).where(tailored, Analysis.tailored_at >= now - timedelta(days=7))),
        "d30": await _count(db, select(func.count()).select_from(Analysis).where(tailored, Analysis.tailored_at >= now - timedelta(days=30))),
    }
    open_tickets = await _count(db, select(func.count()).select_from(SupportTicket).where(SupportTicket.status != "closed"))

    d30 = _first(30, now)
    revenue = None
    if money:
        rev = (await db.execute(select(
            func.coalesce(func.sum(DailyRevenue.settled_usd_cents - DailyRevenue.refunded_usd_cents), 0),
            func.coalesce(func.sum(DailyRevenue.fees_usd_cents), 0)).where(DailyRevenue.day >= d30))).one()
        pro = config.products.get("pro_monthly")
        pro_cents = (pro.prices.get("USD") or 0) if pro else 0
        active_pro = await _count(db, select(func.count()).select_from(Subscription).where(Subscription.status == "active"))
        one_off = await _count(db, select(func.coalesce(func.sum(DailyRevenue.settled_usd_cents - DailyRevenue.refunded_usd_cents), 0))
                               .where(DailyRevenue.day >= d30, DailyRevenue.kind != "subscription"))
        sold = await _count(db, select(func.coalesce(func.sum(CreditTransaction.delta), 0)).where(
            CreditTransaction.reason == "purchase", CreditTransaction.created_at >= now - timedelta(days=30)))
        spent = await _count(db, select(func.coalesce(-func.sum(CreditTransaction.delta), 0)).where(
            CreditTransaction.reason == "analysis_charge", CreditTransaction.created_at >= now - timedelta(days=30)))
        revenue = {"revenue_30d_usd": round(int(rev[0]) / 100, 2), "fees_30d_usd": round(int(rev[1]) / 100, 2),
                   "mrr_equivalent_usd": round((active_pro * pro_cents + one_off) / 100, 2), "active_pro": active_pro,
                   "credits_sold_30d": sold, "credits_consumed_30d": spent}
    cost = None
    if costs:
        usd = Decimal(await db.scalar(select(func.coalesce(func.sum(DailyLlmCost.cost_usd), 0))
                                      .where(DailyLlmCost.day >= d30)) or 0)
        cost = {"llm_cost_30d_usd": round(float(usd), 2)}
        if revenue is not None:
            net = revenue["revenue_30d_usd"] - revenue["fees_30d_usd"]
            cost["gross_margin"] = round((net - float(usd)) / net, 4) if net > 0 else None

    cohort = select(User.id).where(User.created_at >= since).subquery()
    funnel = {
        "landing_views": await _count(db, select(func.coalesce(func.sum(DailyCounter.count), 0)).where(
            DailyCounter.name == "landing.view", DailyCounter.day >= first)),
        "signups": await _count(db, select(func.count()).select_from(cohort)),
        "first_tailoring": await _count(db, select(func.count()).select_from(cohort).where(
            exists().where(Analysis.user_id == cohort.c.id, Analysis.tailored_at.is_not(None)))),
        "downloaded": await _count(db, select(func.count()).select_from(cohort).where(
            exists().where(Download.user_id == cohort.c.id))),
        "paid": await _count(db, select(func.count()).select_from(cohort).where(
            exists().where(Payment.user_id == cohort.c.id, Payment.status.in_(PAID_EVER)))),
    }
    return {
        "days": days, "as_of": await db.scalar(select(func.min(AggregateRun.refreshed_at))),
        "users": users, "tailorings": tailorings, "open_tickets": open_tickets, "revenue": revenue, "costs": cost,
        "series": await _series(db, first, days, money, costs), "funnel": funnel,
    }


@router.get("/overview", dependencies=[Depends(READ_LIMIT)])
async def overview(days: int = Days, viewer: User = Depends(require("staff.access")), db: AsyncSession = Depends(get_db),
                   config: BillingConfig = Depends(billing_config)) -> dict[str, Any]:
    return await overview_data(db, config, viewer, days)


@router.get("/overview/export.csv", dependencies=[Depends(READ_LIMIT)])
async def overview_csv(days: int = Days, viewer: User = Depends(require("staff.access")),
                       db: AsyncSession = Depends(get_db)) -> Response:
    """The daily series as CSV (revenue and cost columns only for roles that see them)."""
    money, costs = can(viewer.role, "billing.read"), can(viewer.role, "costs.read")
    rows = await _series(db, _first(days, datetime.now(UTC)), days, money, costs)
    buf = io.StringIO()
    cols = ["day", "signups"] + (["revenue_usd"] if money else []) + (["cost_usd"] if costs else [])
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="overview-{days}d.csv"'})


# --- integrations -------------------------------------------------------------------------------


def _effective(name: str, check: IntegrationCheck | None) -> str:
    if not integ.configured(name):
        return "not_configured"
    return check.status if check else "configured"


@router.get("/integrations", dependencies=[Depends(READ_LIMIT)])
async def integrations(viewer: User = Depends(require("integrations.read")),
                       db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    checks = {c.name: c for c in await db.scalars(select(IntegrationCheck))}
    hint = can(viewer.role, "secrets.hint")
    out = []
    for name in integ.NAMES:
        c = checks.get(name)
        out.append({
            "name": name, "status": _effective(name, c), "checkable": name in integ.CHECKS,
            "checked_at": c.checked_at if c else None, "last_ok_at": c.last_ok_at if c else None,
            "error_code": c.error_code if c else None, "check_detail": c.detail if c else {},
            "facts": await integ.facts(db, name, now), "secrets": integ.secrets(name, hint_allowed=hint),
        })
    return out


@router.post("/integrations/{name}/check", dependencies=WRITE)
async def run_check(name: str, request: Request, actor: User = Depends(require("integrations.read")),
                    db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if name not in integ.CHECKS:
        raise HTTPException(status_code=404, detail="not_found")
    c = await integ.run_check(db, name, actor.id)
    audit.record(db, actor, "integrations.check", request=request, target_type="integration", target_id=name,
                 after={"status": c.status, "error_code": c.error_code})
    await db.commit()
    return {"name": name, "status": c.status, "checked_at": c.checked_at, "last_ok_at": c.last_ok_at,
            "error_code": c.error_code, "check_detail": c.detail}


# --- webhook log --------------------------------------------------------------------------------


@router.get("/webhooks", dependencies=[Depends(READ_LIMIT)])
async def webhook_log(_: User = Depends(require("integrations.read")), db: AsyncSession = Depends(get_db),
                      status: Literal["all", "failing", "processed", "ignored", "flagged"] = "all",
                      page: int = Query(1, ge=1, le=10_000), page_size: int = Query(25, ge=1, le=100)) -> dict[str, Any]:
    """Recent provider events. The stored payload of a failing event is never returned."""
    stmt = select(ProcessedWebhookEvent)
    if status == "failing":
        stmt = stmt.where(ProcessedWebhookEvent.processed_at.is_(None))
    elif status != "all":
        stmt = stmt.where(ProcessedWebhookEvent.outcome == status)
    total = await _count(db, select(func.count()).select_from(stmt.subquery()))
    rows = await db.scalars(stmt.order_by(ProcessedWebhookEvent.received_at.desc())
                            .offset((page - 1) * page_size).limit(page_size))
    items = [{"id": e.event_id, "provider": e.provider, "event_type": e.event_type, "occurred_at": e.occurred_at,
              "received_at": e.received_at, "processed_at": e.processed_at,
              "status": e.outcome or "failing", "failures": e.failures, "last_error": e.last_error,
              "replayable": e.processed_at is None and e.payload is not None} for e in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/webhooks/{event_id}/replay", dependencies=WRITE)
async def replay(event_id: str, body: Reason, request: Request, actor: User = Depends(require("billing.write")),
                 db: AsyncSession = Depends(get_db), config: BillingConfig = Depends(billing_config),
                 provider: PaymentProvider = Depends(payment_provider)) -> dict[str, Any]:
    """Run a failed delivery again from its stored, verified data. Idempotent."""
    try:
        outcome = await webhooks.replay(db, provider, config, event_id)
    except webhooks.NotReplayable:
        raise HTTPException(status_code=409, detail="not_replayable") from None
    except Exception:  # noqa: BLE001 - recorded as another failure by process_webhook
        outcome = "failed"
    await db.refresh(actor)  # the replay's rollbacks expired it
    audit.record(db, actor, "billing.webhook_replay", request=request, target_type="webhook_event",
                 target_id=event_id[:64], reason=body.reason, after={"outcome": outcome})
    await db.commit()
    return {"outcome": outcome}


# --- quality ------------------------------------------------------------------------------------

LIFT_BUCKETS = (("below 0", None, 0), ("0", 0, 0.5), ("1 to 5", 0.5, 5.5), ("6 to 10", 5.5, 10.5),
                ("11 to 20", 10.5, 20.5), ("over 20", 20.5, None))
COUNTS = ("bullets_generated", "bullets_blocked", "bullets_flagged", "bullets_approved", "bullets_rejected",
          "flag_overrides")


@router.get("/quality", dependencies=[Depends(READ_LIMIT)])
async def quality(days: int = Days, _: User = Depends(require("quality.read")),
                  db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    now = datetime.now(UTC)
    first = _first(days, now)
    since = _start(first)
    in_window = Analysis.created_at >= since
    sums = (await db.execute(select(*[func.coalesce(func.sum(getattr(Analysis, c)), 0) for c in COUNTS],
                                    func.count().filter(Analysis.bullets_generated.is_not(None)),
                                    func.count().filter(Analysis.bullets_approved.is_not(None))).where(in_window))).one()
    totals = {c: int(v) for c, v in zip(COUNTS, sums[:6], strict=True)}
    totals |= {"analyses_tailored": int(sums[6]), "analyses_downloaded": int(sums[7])}
    gen, blocked, approved = totals["bullets_generated"], totals["bullets_blocked"], totals["bullets_approved"]
    rates = {"flagged": round(totals["bullets_flagged"] / gen, 4) if gen else None,
             "blocked": round(blocked / (gen + blocked), 4) if gen + blocked else None,
             "override": round(totals["flag_overrides"] / approved, 4) if approved else None}

    day = _utc_day(Analysis.created_at)
    trend = {(first + timedelta(days=i)).isoformat(): {"day": (first + timedelta(days=i)).isoformat(), "generated": 0,
                                                       "flagged": 0, "blocked": 0, "overrides": 0} for i in range(days)}
    for d, g, f, b, o in (await db.execute(select(
            day, func.coalesce(func.sum(Analysis.bullets_generated), 0), func.coalesce(func.sum(Analysis.bullets_flagged), 0),
            func.coalesce(func.sum(Analysis.bullets_blocked), 0), func.coalesce(func.sum(Analysis.flag_overrides), 0))
            .where(in_window).group_by(day))).all():
        if d.isoformat() in trend:
            trend[d.isoformat()].update(generated=int(g), flagged=int(f), blocked=int(b), overrides=int(o))

    parse = dict((await db.execute(select(DailyCounter.name, func.sum(DailyCounter.count)).where(
        DailyCounter.day >= first, DailyCounter.name.like("resume_parse.%")).group_by(DailyCounter.name))).all())
    ok = int(parse.get("resume_parse.ok", 0))
    failed = {k.removeprefix("resume_parse.failed."): int(v) for k, v in parse.items() if k.startswith("resume_parse.failed.")}
    warnings = {k.removeprefix("resume_parse.warning."): int(v) for k, v in parse.items() if k.startswith("resume_parse.warning.")}
    attempts = ok + sum(failed.values())

    lift = Analysis.ats_after - Analysis.ats_before
    bucket = case(*[((lift < hi) if lo is None else (lift >= lo) if hi is None else (lift >= lo) & (lift < hi), label)
                    for label, lo, hi in LIFT_BUCKETS])
    has_lift = (Analysis.ats_before.is_not(None), Analysis.ats_after.is_not(None), in_window)
    by_bucket = dict((await db.execute(select(bucket, func.count()).where(*has_lift).group_by(bucket))).all())
    median = await db.scalar(select(func.percentile_cont(0.5).within_group(lift)).where(*has_lift))

    reports = (await db.execute(select(SupportTicket.id, SupportTicket.subject, SupportTicket.status,
                                       SupportTicket.analysis_id, SupportTicket.created_at)
                                .where(SupportTicket.category == "fabrication_report")
                                .order_by((SupportTicket.status == "closed").asc(), SupportTicket.created_at.desc())
                                .limit(50))).all()
    return {
        "days": days, "verifier": {"totals": totals, "rates": rates, "trend": list(trend.values())},
        "parsing": {"attempts": attempts, "ok": ok, "failed": failed, "failure_rate": round(sum(failed.values()) / attempts, 4)
                    if attempts else None, "warnings": warnings},
        "ats_lift": {"buckets": [{"label": label, "count": int(by_bucket.get(label, 0))} for label, _, _ in LIFT_BUCKETS],
                     "median": round(float(median), 1) if median is not None else None},
        "fabrication_reports": [{"id": r.id, "subject": r.subject, "status": r.status, "analysis_id": r.analysis_id,
                                 "created_at": r.created_at} for r in reports],
    }


# --- config view (read-only: billing.toml and the published notices) ----------------------------


@router.get("/config", dependencies=[Depends(READ_LIMIT)])
async def config_view(_: User = Depends(require("audit.read")), db: AsyncSession = Depends(get_db),
                      base: BillingConfig = Depends(billing_config)) -> dict[str, Any]:
    config = await runtime.live_config(db, base)
    notices = await db.scalars(select(ConsentNotice).order_by(ConsentNotice.purpose, ConsentNotice.published_at.desc()))
    return {
        "products": [{"key": p.key, "name": p.name, "kind": p.kind, "enabled": p.enabled, "credits": p.credits,
                      "pass_days": p.pass_days, "fair_use_cap": p.fair_use_cap, "interval": p.interval,
                      "prices": p.prices} for p in config.products.values()],
        "free_analyses_per_month": config.free.analyses_per_month,
        "credits_per_download": config.downloads.credits_per_download,
        "redownload_free_days": config.downloads.redownload_free_days,
        "claude_per_day": {"free": config.analyses.claude_analyses_per_day, "paid": config.analyses.paid_claude_analyses_per_day},
        "retention": {"analysis_days": config.retention.analysis_days, "download_days": config.retention.download_days},
        "llm_prices": sorted(config.llm_prices),
        "notices": [{"purpose": n.purpose, "version": n.version, "language": n.language, "published_at": n.published_at,
                     "current": n.retired_at is None, "body_url": n.body_url} for n in notices],
    }
