"""/api/admin/revenue and /api/admin/costs.

History comes from the daily rollups (app.billing.aggregates; `as_of` says when they
last ran), so the pages stay fast. Live reads are bounded by the window: transactions,
cost per analysis and top-cost users.

Revenue needs billing.read; refunds need billing.write, go through the payment provider
(Dodo settles them and the webhook updates the payment) and are audited. Disputes have
no API: they're answered in Dodo's dashboard. Costs need costs.read; budgets and the kill
switch are runtime settings (settings.write, /api/admin/settings).
"""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import audit
from app.admin import settings as runtime
from app.api.admin import READ_LIMIT, WRITE, Reason
from app.api.billing import billing_config, payment_provider
from app.auth.roles import require
from app.billing import budget
from app.billing.config import BillingConfig
from app.billing.providers import PaymentProvider
from app.billing.providers.base import PaymentError
from app.db.models import (
    AggregateRun,
    Analysis,
    BillingReview,
    CreditTransaction,
    DailyLlmCost,
    DailyRevenue,
    LlmUsage,
    Payment,
    Subscription,
    User,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/admin")
Days = Query(30, ge=1, le=730)


def _since(days: int, now: datetime) -> date:
    return (now - timedelta(days=days - 1)).date()


async def _as_of(db: AsyncSession, name: str) -> datetime | None:
    return await db.scalar(select(AggregateRun.refreshed_at).where(AggregateRun.name == name))


def _usd(cents: int | Decimal) -> float:
    return round(float(cents) / 100, 2)


# --- revenue -------------------------------------------------------------------------------------


@router.get("/revenue", dependencies=[Depends(READ_LIMIT)])
async def revenue(days: int = Days, _: User = Depends(require("billing.read")), db: AsyncSession = Depends(get_db),
                  config: BillingConfig = Depends(billing_config)) -> dict[str, Any]:
    now = datetime.now(UTC)
    first = _since(days, now)
    rows = list(await db.scalars(select(DailyRevenue).where(DailyRevenue.day >= first).order_by(DailyRevenue.day)))
    settled = sum(r.settled_usd_cents for r in rows)
    refunded = sum(r.refunded_usd_cents for r in rows)
    fees = sum(r.fees_usd_cents for r in rows)
    by_product: dict[str, dict] = {}
    by_currency: dict[str, dict] = {}
    # Every day in the window, so a quiet day reads as zero rather than being skipped.
    daily: dict[str, dict] = {(first + timedelta(days=i)).isoformat(): {"day": (first + timedelta(days=i)).isoformat(),
                                                                        "gross_usd": 0, "net_usd": 0} for i in range(days)}
    for r in rows:
        p = by_product.setdefault(r.product_key, {"product_key": r.product_key, "kind": r.kind, "payments": 0,
                                                  "gross_usd": 0, "refunds_usd": 0, "fees_usd": 0, "net_usd": 0})
        p["payments"] += r.payments
        p["gross_usd"] += r.settled_usd_cents
        p["refunds_usd"] += r.refunded_usd_cents
        p["fees_usd"] += r.fees_usd_cents
        c = by_currency.setdefault(r.currency, {"currency": r.currency, "payments": 0, "gross_minor": 0, "refunded_minor": 0})
        c["payments"] += r.payments
        c["gross_minor"] += r.gross_minor
        c["refunded_minor"] += r.refunded_minor
        d = daily[r.day.isoformat()]
        d["gross_usd"] += r.settled_usd_cents
        d["net_usd"] += r.settled_usd_cents - r.refunded_usd_cents - r.fees_usd_cents
    for p in by_product.values():
        p["net_usd"] = p["gross_usd"] - p["refunds_usd"] - p["fees_usd"]
        for k in ("gross_usd", "refunds_usd", "fees_usd", "net_usd"):
            p[k] = _usd(p[k])
    for d in daily.values():
        d["gross_usd"], d["net_usd"] = _usd(d["gross_usd"]), _usd(d["net_usd"])

    since_dt = datetime(first.year, first.month, first.day, tzinfo=UTC)
    subs = {s: int(n) for s, n in (await db.execute(
        select(Subscription.status, func.count()).group_by(Subscription.status))).all()}
    cancelled = int(await db.scalar(select(func.count()).select_from(Subscription).where(
        Subscription.status == "cancelled", Subscription.updated_at >= since_dt)) or 0)
    due = int(await db.scalar(select(func.count()).select_from(Subscription).where(
        Subscription.status == "active", Subscription.cancel_at_period_end.is_(False),
        Subscription.current_period_end.between(now, now + timedelta(days=7)))) or 0)
    active = subs.get("active", 0)

    granted = int(await db.scalar(select(func.coalesce(func.sum(CreditTransaction.delta), 0)).where(
        CreditTransaction.reason == "referral", CreditTransaction.created_at >= since_dt)) or 0)
    granted_all = int(await db.scalar(select(func.coalesce(func.sum(CreditTransaction.delta), 0)).where(
        CreditTransaction.reason == "referral")) or 0)
    pack = next((p for p in config.products.values() if p.kind == "credit_pack" and p.credits), None)
    per_credit = (pack.prices.get("USD", 0) / pack.credits) if pack else 0
    return {
        "as_of": await _as_of(db, "revenue"), "days": days,
        "totals": {"gross_usd": _usd(settled), "refunds_usd": _usd(refunded), "fees_usd": _usd(fees),
                   "net_usd": _usd(settled - refunded), "net_after_fees_usd": _usd(settled - refunded - fees),
                   "payments": sum(r.payments for r in rows), "disputes": sum(r.disputes for r in rows),
                   "unsettled": sum(r.unsettled for r in rows)},
        "fees_are_estimates": not config.fees.dodo.settlement_is_net_of_fees,
        "by_product": sorted(by_product.values(), key=lambda p: -p["gross_usd"]),
        "by_currency": sorted(by_currency.values(), key=lambda c: c["currency"]),
        "daily": list(daily.values()),
        "subscriptions": {"active": active, "by_status": subs, "cancelled_in_window": cancelled,
                          "churn_rate": round(cancelled / (active + cancelled), 4) if active + cancelled else None,
                          "renewals_due_7d": due},
        "referral_liability": {"credits_granted_in_window": granted, "credits_granted_total": granted_all,
                               "est_value_usd": _usd(granted * per_credit), "per_credit_usd": _usd(per_credit)},
    }


class PaymentRow(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_email: str | None
    product_key: str
    kind: str
    status: str
    mode: str
    currency: str | None
    amount_minor: int | None
    refunded_amount_minor: int
    provider_payment_id: str | None
    disputed: bool
    created_at: datetime
    paid_at: datetime | None


@router.get("/revenue/payments", dependencies=[Depends(READ_LIMIT)])
async def payments(_: User = Depends(require("billing.read")), db: AsyncSession = Depends(get_db),
                   status: str | None = Query(None, max_length=40), product_key: str | None = Query(None, max_length=80),
                   q: str | None = Query(None, max_length=200), page: int = Query(1, ge=1, le=10_000),
                   page_size: int = Query(25, ge=1, le=100)) -> dict[str, Any]:
    disputed = exists().where(BillingReview.payment_id == Payment.id, BillingReview.kind == "dispute_opened")
    stmt = select(Payment, User.email, disputed.label("disputed")).outerjoin(User, User.id == Payment.user_id)
    if status:
        stmt = stmt.where(Payment.status == status)
    if product_key:
        stmt = stmt.where(Payment.product_key == product_key)
    if q:
        stmt = stmt.where((Payment.provider_payment_id == q.strip()) | User.email.ilike(f"%{q.strip()}%"))
    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (await db.execute(stmt.order_by(Payment.created_at.desc(), Payment.id).offset((page - 1) * page_size)
                             .limit(page_size))).all()
    items = [PaymentRow(id=p.id, user_id=p.user_id, user_email=e, product_key=p.product_key, kind=p.kind, status=p.status,
                        mode=p.mode, currency=p.currency, amount_minor=p.amount_minor,
                        refunded_amount_minor=p.refunded_amount_minor, provider_payment_id=p.provider_payment_id,
                        disputed=bool(d), created_at=p.created_at, paid_at=p.paid_at) for p, e, d in rows]
    return {"items": [i.model_dump(mode="json") for i in items], "total": total, "page": page, "page_size": page_size}


class RefundIn(Reason):
    amount_minor: int | None = Field(default=None, ge=1)  # None: refund what's left in full


@router.post("/revenue/payments/{payment_id}/refund", dependencies=WRITE)
async def refund(payment_id: uuid.UUID, body: RefundIn, request: Request, actor: User = Depends(require("billing.write")),
                 db: AsyncSession = Depends(get_db), config: BillingConfig = Depends(billing_config),
                 provider: PaymentProvider = Depends(payment_provider)) -> dict[str, Any]:
    """Ask Dodo to refund. Dodo settles it and its webhook updates the payment (and takes
    back the credits per the refund policy); this records the request in the audit log."""
    p = await db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if p is None:
        raise HTTPException(status_code=404, detail="not_found")
    if p.status not in ("paid", "partially_refunded") or not p.provider_payment_id or not p.amount_minor:
        raise HTTPException(status_code=409, detail="not_refundable")
    left = p.amount_minor - p.refunded_amount_minor
    if body.amount_minor is not None and body.amount_minor > left:
        raise HTTPException(status_code=422, detail="more_than_paid")
    partial = body.amount_minor is not None and body.amount_minor < left
    product = config.products.get(p.product_key)
    item = product.dodo_product_id.for_mode(p.mode) if product and partial else None
    if partial and not item:
        raise HTTPException(status_code=409, detail="partial_needs_product_id")
    try:
        result = await provider.refund(p.provider_payment_id, reason=body.reason[:200],
                                       amount_minor=body.amount_minor if partial else None, item_id=item,
                                       metadata={"payment_id": str(p.id), "by": "admin"})
    except (PaymentError, ValueError):
        await db.rollback()
        raise HTTPException(status_code=502, detail="refund_failed") from None
    audit.record(db, actor, "billing.refund", request=request, target_type="payment", target_id=p.id,
                 reason=body.reason, before={"status": p.status, "refunded_minor": p.refunded_amount_minor},
                 after={"requested_minor": body.amount_minor or left, "currency": p.currency, "partial": partial,
                        "provider_refund_id": result.provider_refund_id, "provider_status": result.status})
    await db.commit()
    return {"provider_refund_id": result.provider_refund_id, "status": result.status}


# --- costs ---------------------------------------------------------------------------------------


def _bucket(d: date, granularity: str) -> str:
    if granularity == "week":
        return (d - timedelta(days=d.weekday())).isoformat()
    if granularity == "month":
        return f"{d:%Y-%m}"
    return d.isoformat()


@router.get("/costs", dependencies=[Depends(READ_LIMIT)])
async def costs(days: int = Days, granularity: Literal["day", "week", "month"] = "day",
                _: User = Depends(require("costs.read")), db: AsyncSession = Depends(get_db),
                config: BillingConfig = Depends(billing_config)) -> dict[str, Any]:
    now = datetime.now(UTC)
    first = _since(days, now)
    since_dt = datetime(first.year, first.month, first.day, tzinfo=UTC)
    rows = list(await db.scalars(select(DailyLlmCost).where(DailyLlmCost.day >= first)))
    total = sum((r.cost_usd for r in rows), Decimal(0))
    series: dict[str, list] = {_bucket(first + timedelta(days=i), granularity): [Decimal(0), 0] for i in range(days)}
    groups: dict[str, dict[str, list]] = {"stage": defaultdict(lambda: [Decimal(0), 0]),
                                          "model": defaultdict(lambda: [Decimal(0), 0]),
                                          "entitlement": defaultdict(lambda: [Decimal(0), 0])}
    for r in rows:
        series[_bucket(r.day, granularity)][0] += r.cost_usd
        series[_bucket(r.day, granularity)][1] += r.calls
        for g in groups:
            acc = groups[g][getattr(r, g)]
            acc[0] += r.cost_usd
            acc[1] += r.calls

    def listed(g: str) -> list[dict]:
        return sorted(({"key": k, "cost_usd": round(float(v[0]), 4), "calls": v[1]} for k, v in groups[g].items()),
                      key=lambda x: -x["cost_usd"])

    # Live, bounded by the window: per analysis, top users.
    per = (select(LlmUsage.analysis_id, func.sum(LlmUsage.cost_usd).label("c")).where(
        LlmUsage.created_at >= since_dt, LlmUsage.analysis_id.is_not(None)).group_by(LlmUsage.analysis_id).subquery())
    avg, p95, n = (await db.execute(select(func.avg(per.c.c), func.percentile_cont(0.95).within_group(per.c.c),
                                           func.count()))).one()
    top = (await db.execute(
        select(LlmUsage.user_id, User.email, func.coalesce(func.sum(LlmUsage.cost_usd), 0).label("c"), func.count())
        .join(User, User.id == LlmUsage.user_id).where(LlmUsage.created_at >= since_dt)
        .group_by(LlmUsage.user_id, User.email).order_by(func.sum(LlmUsage.cost_usd).desc().nulls_last()).limit(10))).all()

    rev = sum((r.settled_usd_cents - r.refunded_usd_cents - r.fees_usd_cents)
              for r in await db.scalars(select(DailyRevenue).where(DailyRevenue.day >= first)))
    analyses = int(await db.scalar(select(func.count()).select_from(Analysis).where(Analysis.created_at >= since_dt)) or 0)
    s = await budget.spend(db, now)
    settings = (await runtime.read_all(db)).values
    calls = sum(r.calls for r in rows)
    failed = sum(r.failed for r in rows)
    return {
        "as_of": await _as_of(db, "llm_costs"), "days": days, "granularity": granularity,
        "total_usd": round(float(total), 4), "calls": calls, "failed_calls": failed,
        "error_rate": round(failed / calls, 4) if calls else None,
        "wasted_usd": round(float(sum((r.wasted_usd for r in rows), Decimal(0))), 4),
        "unpriced_calls": sum(r.unpriced_calls for r in rows),
        "free_tier_usd": round(float(groups["entitlement"]["free"][0]), 4),
        "series": [{"period": k, "cost_usd": round(float(v[0]), 4), "calls": v[1]} for k, v in sorted(series.items())],
        "by_step": listed("stage"), "by_model": listed("model"), "by_plan": listed("entitlement"),
        "per_analysis": {"analyses": int(n), "avg_usd": round(float(avg), 4) if avg is not None else None,
                         "p95_usd": round(float(p95), 4) if p95 is not None else None},
        "top_users": [{"user_id": u, "email": e, "cost_usd": round(float(c), 4), "calls": k} for u, e, c, k in top],
        "margin": {"net_revenue_usd": _usd(rev), "analyses": analyses, "cost_usd": round(float(total), 4),
                   "revenue_per_analysis_usd": round(rev / 100 / analyses, 4) if analyses else None,
                   "cost_per_analysis_usd": round(float(total) / analyses, 4) if analyses else None},
        "budget": {"today_usd": round(float(s.today_usd), 4), "month_usd": round(float(s.month_usd), 4),
                   "daily_budget_usd": float(s.daily_budget_usd), "monthly_budget_usd": float(s.monthly_budget_usd),
                   "kill_switch": s.kill_switch, "paused": await budget.pause_reason(db, now),
                   "analyses_paused": settings.analyses_paused},
        "per_user_daily_caps": {"free": config.analyses.claude_analyses_per_day,
                                "paid": config.analyses.paid_claude_analyses_per_day},
        "prices": [{"model": m, "input": p.input, "output": p.output, "cache_read": p.cache_read,
                    "cache_write": p.cache_write} for m, p in sorted(config.llm_prices.items())],
    }
