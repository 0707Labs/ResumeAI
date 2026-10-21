"""Admin billing metrics: payments, refunds, disputes, credits, LLM cost, margin, alerts.

Money: revenue uses Dodo's settlement figures, which arrive in USD for INR and most
other currencies. Settlements in another currency are listed but left out of the USD
margin. Dodo reports no fee per payment, so fees are estimated from billing.toml
[fees.dodo]; the admin view labels them as estimates.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, case, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.config import BillingConfig
from app.db.models import (
    BillingReview,
    CreditTransaction,
    LlmUsage,
    Payment,
    ProcessedWebhookEvent,
    User,
)

PAID_EVER = ("paid", "partially_refunded", "refunded", "disputed")


@dataclass
class Alert:
    kind: str
    severity: str  # "critical" | "warning"
    message: str


def estimated_fee_usd_cents(config: BillingConfig, payment: Payment) -> int:
    """Dodo's fee for one payment, estimated: % of the settled amount plus a fixed fee,
    plus the refund fee per refund (Dodo keeps the original fee on refunds). The dispute
    fee is added by the caller."""
    f = config.fees.dodo
    base = payment.settlement_amount_minor or 0  # USD cents when settled in USD
    if payment.currency == "INR":
        pct, fixed = f.india_pct, f.india_fixed_usd_cents
    else:
        pct, fixed = f.base_pct + f.international_extra_pct, f.base_fixed_usd_cents
    if payment.kind == "subscription":
        pct += f.subscription_extra_pct
    fee = base * pct / 100 + fixed
    if payment.refunded_amount_minor:
        fee += f.refund_fixed_usd_cents * max(1, len(payment.refund_ids))
    return round(fee)


def net_revenue_usd_cents(config: BillingConfig, payment: Payment, disputed: bool) -> tuple[int, int, int]:
    """(settled excluding tax, refunded share, estimated fees) in USD cents for one payment."""
    settled = (payment.settlement_amount_minor or 0) - (payment.settlement_tax_minor or 0)
    refunded = 0
    if payment.refunded_amount_minor and payment.amount_minor:
        refunded = round(settled * min(1, payment.refunded_amount_minor / payment.amount_minor))
    fees = 0 if config.fees.dodo.settlement_is_net_of_fees else estimated_fee_usd_cents(config, payment)
    if disputed:
        fees += config.fees.dodo.dispute_fixed_usd_cents
    return settled, refunded, fees


async def llm_stats(db: AsyncSession, since: datetime) -> dict:
    row = (await db.execute(
        select(func.count(), func.coalesce(func.sum(LlmUsage.cost_usd), 0),
               func.count(distinct(LlmUsage.analysis_id)),
               func.count().filter(LlmUsage.cost_usd.is_(None)))
        .where(LlmUsage.created_at >= since)
    )).one()
    calls, total, analyses, unpriced = row
    per = (select(func.sum(LlmUsage.cost_usd).label("cost_usd"))
           .where(LlmUsage.created_at >= since, LlmUsage.analysis_id.is_not(None))
           .group_by(LlmUsage.analysis_id).subquery())
    per_analysis = await db.scalar(select(func.avg(per.c.cost_usd)))
    by_model = (await db.execute(
        select(LlmUsage.model, func.count(), func.coalesce(func.sum(LlmUsage.cost_usd), 0))
        .where(LlmUsage.created_at >= since).group_by(LlmUsage.model).order_by(LlmUsage.model)
    )).all()
    day = cast(func.timezone("UTC", LlmUsage.created_at), Date)
    daily = (await db.execute(
        select(day, func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(LlmUsage.created_at >= since)
        .group_by(day).order_by(day)
    )).all()
    return {
        "calls": calls,
        "total_cost_usd": float(total),
        "analyses": analyses,
        "avg_cost_per_analysis_usd": float(per_analysis) if per_analysis is not None else None,
        "unpriced_calls": unpriced,
        "by_model": [{"model": m, "calls": c, "cost_usd": float(v)} for m, c, v in by_model],
        "daily": [{"day": d.isoformat(), "cost_usd": float(v)} for d, v in daily],
    }


async def credit_stats(db: AsyncSession, since: datetime) -> dict:
    def total(reason: str):
        return func.coalesce(func.sum(case((CreditTransaction.reason == reason, CreditTransaction.delta), else_=0)), 0)

    sold, charged, returned, reversed_ = (await db.execute(
        select(total("purchase"), total("analysis_charge"), total("refund"), total("purchase_reversal"))
        .where(CreditTransaction.created_at >= since)
    )).one()
    outstanding = await db.scalar(select(func.coalesce(func.sum(User.credits_balance), 0)))
    return {"sold": int(sold), "consumed": int(-charged - returned), "reversed": int(-reversed_),
            "outstanding": int(outstanding)}


async def margin_by_plan(db: AsyncSession, config: BillingConfig, since: datetime,
                         avg_cost_per_analysis: float | None) -> list[dict]:
    payments = list(await db.scalars(
        select(Payment).where(Payment.status.in_(PAID_EVER), Payment.paid_at >= since)
    ))
    disputed = set(await db.scalars(
        select(BillingReview.payment_id).where(BillingReview.kind == "dispute_opened")
    ))
    plans: dict[str, dict] = {}
    for p in payments:
        plan = plans.setdefault(p.product_key, {
            "product_key": p.product_key, "units": 0, "settled_usd_cents": 0, "refunded_usd_cents": 0,
            "fees_usd_cents": 0, "other_currency_units": 0, "runs_if_fully_used": 0,
        })
        plan["units"] += 1
        if p.settlement_currency not in (None, "USD"):
            plan["other_currency_units"] += 1
            continue
        settled, refunded, fees = net_revenue_usd_cents(config, p, p.id in disputed)
        plan["settled_usd_cents"] += settled
        plan["refunded_usd_cents"] += refunded
        plan["fees_usd_cents"] += fees
        plan["runs_if_fully_used"] += p.snapshot.get("credits") or p.snapshot.get("fair_use_cap") or 0
    out = []
    for plan in plans.values():
        net = plan["settled_usd_cents"] - plan["refunded_usd_cents"] - plan["fees_usd_cents"]
        worst_llm = (round(plan["runs_if_fully_used"] * avg_cost_per_analysis * 100)
                     if avg_cost_per_analysis is not None else None)
        out.append({**plan, "net_usd_cents": net, "llm_cost_if_fully_used_usd_cents": worst_llm,
                    "margin_if_fully_used_usd_cents": net - worst_llm if worst_llm is not None else None})
    return sorted(out, key=lambda p: p["product_key"])


async def alerts(db: AsyncSession, config: BillingConfig, now: datetime | None = None) -> list[Alert]:
    now = now or datetime.now(UTC)
    found: list[Alert] = []
    failing = await db.scalar(select(func.count()).select_from(ProcessedWebhookEvent).where(
        ProcessedWebhookEvent.processed_at.is_(None),
        ProcessedWebhookEvent.failures >= config.alerts.webhook_failures,
    ))
    if failing:
        found.append(Alert("webhook_failing", "critical",
                           f"{failing} webhook event(s) failed {config.alerts.webhook_failures}+ times "
                           "and are still unprocessed. Purchases may not have been granted."))
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    spend = await db.scalar(select(func.coalesce(func.sum(LlmUsage.cost_usd), 0))
                            .where(LlmUsage.created_at >= midnight))
    if Decimal(spend) > Decimal(str(config.alerts.daily_llm_spend_usd)):
        found.append(Alert("llm_spend", "warning",
                           f"LLM spend today is ${Decimal(spend):.2f}, over the "
                           f"${config.alerts.daily_llm_spend_usd:.2f} threshold."))
    unpriced = await db.scalar(select(func.count()).select_from(LlmUsage).where(
        LlmUsage.cost_usd.is_(None), LlmUsage.created_at >= midnight))
    if unpriced:
        found.append(Alert("llm_unpriced", "warning",
                           f"{unpriced} Claude call(s) today used a model with no price in billing.toml."))
    return found


async def overview(db: AsyncSession, config: BillingConfig, days: int) -> dict:
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    llm = await llm_stats(db, since)
    status_counts = dict((await db.execute(
        select(Payment.status, func.count()).where(Payment.created_at >= since).group_by(Payment.status)
    )).all())
    recent = (await db.execute(
        select(Payment, User.email).outerjoin(User, User.id == Payment.user_id)
        .where(Payment.created_at >= since, Payment.status != "created")
        .order_by(Payment.created_at.desc()).limit(50)
    )).all()
    reviews = list(await db.scalars(
        select(BillingReview).where(BillingReview.resolved_at.is_(None)).order_by(BillingReview.created_at.desc())
    ))
    failing = list(await db.scalars(
        select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.processed_at.is_(None),
                                            ProcessedWebhookEvent.failures > 0)
        .order_by(ProcessedWebhookEvent.received_at.desc()).limit(50)
    ))
    return {
        "days": days,
        "payment_counts": status_counts,
        "payments": [{
            "id": p.id, "email": email, "product_key": p.product_key, "status": p.status,
            "amount_minor": p.amount_minor, "currency": p.currency, "refunded_amount_minor": p.refunded_amount_minor,
            "provider_payment_id": p.provider_payment_id, "created_at": p.created_at, "paid_at": p.paid_at,
        } for p, email in recent],
        "credits": await credit_stats(db, since),
        "llm": llm,
        "margin": await margin_by_plan(db, config, since, llm["avg_cost_per_analysis_usd"]),
        "fees_are_estimates": not config.fees.dodo.settlement_is_net_of_fees,
        "reviews": [{"id": r.id, "kind": r.kind, "payment_id": r.payment_id, "detail": r.detail,
                     "created_at": r.created_at} for r in reviews],
        "failing_webhooks": [{"event_id": e.event_id, "event_type": e.event_type, "failures": e.failures,
                              "last_error": e.last_error, "received_at": e.received_at} for e in failing],
        "alerts": [a.__dict__ for a in await alerts(db, config, now)],
    }


async def resolve_review(db: AsyncSession, review_id: uuid.UUID) -> bool:
    review = await db.get(BillingReview, review_id)
    if review is None or review.resolved_at is not None:
        return False
    review.resolved_at = datetime.now(UTC)
    await db.commit()
    return True
