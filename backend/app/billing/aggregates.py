"""Daily rollups for the admin dashboard: Claude costs and revenue.

`refresh(db, config, days)` recomputes the last `days` UTC days (today included) from
llm_usage and payments, replacing those days' rows in one transaction, so it's safe to
run as often as you like and a late webhook or refund is picked up on the next run. Run
it from cron every 15 minutes:

    */15 * * * * cd /srv/resume-tailor/backend && .venv/bin/python -m app.billing.cli refresh-aggregates

and occasionally with --days 400 to rebuild history. Revenue uses the same per-payment
arithmetic as /admin/billing (app.billing.admin.net_revenue_usd_cents), so the numbers
agree. Fees are estimates from billing.toml unless Dodo's settlement is net of fees.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, case, cast, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.admin import PAID_EVER, net_revenue_usd_cents
from app.billing.config import BillingConfig
from app.billing.costs import pipeline_step
from app.db.models import AggregateRun, Analysis, BillingReview, DailyLlmCost, DailyRevenue, LlmUsage, Payment

WASTED = ("refused", "truncated", "invalid")


def _utc_day(column):
    return cast(func.timezone("UTC", column), Date)


async def refresh(db: AsyncSession, config: BillingConfig, days: int = 3, now: datetime | None = None) -> dict:
    """Recompute the last `days` days. Commits. Returns row counts written."""
    now = now or datetime.now(UTC)
    first: date = (now - timedelta(days=days - 1)).date()
    since = datetime(first.year, first.month, first.day, tzinfo=UTC)

    # Claude costs, per day x pipeline step x model x entitlement.
    day = _utc_day(LlmUsage.created_at)
    cost = func.coalesce(LlmUsage.cost_usd, 0)
    rows = (await db.execute(
        select(day.label("day"), LlmUsage.stage, LlmUsage.model,
               func.coalesce(Analysis.entitlement, "none").label("entitlement"),
               func.count(), func.count().filter(LlmUsage.status != "ok"),
               func.coalesce(func.sum(LlmUsage.input_tokens), 0), func.coalesce(func.sum(LlmUsage.output_tokens), 0),
               func.coalesce(func.sum(cost), 0),
               func.coalesce(func.sum(case((LlmUsage.status.in_(WASTED), cost), else_=0)), 0),
               func.count().filter(LlmUsage.cost_usd.is_(None)))
        .outerjoin(Analysis, Analysis.id == LlmUsage.analysis_id)
        .where(LlmUsage.created_at >= since)
        .group_by(day, LlmUsage.stage, LlmUsage.model, "entitlement"))).all()
    llm: dict[tuple, list] = defaultdict(lambda: [0, 0, 0, 0, Decimal(0), Decimal(0), 0])
    for d, stage, model, ent, calls, failed, tin, tout, usd, waste, unpriced in rows:
        acc = llm[(d, pipeline_step(stage), model, ent)]
        for i, v in enumerate((calls, failed, tin, tout, Decimal(usd), Decimal(waste), unpriced)):
            acc[i] += v

    # Revenue, per day paid x product x currency.
    disputed = set(await db.scalars(select(BillingReview.payment_id).where(BillingReview.kind == "dispute_opened")))
    revenue: dict[tuple, dict] = {}
    for p in await db.scalars(select(Payment).where(Payment.status.in_(PAID_EVER), Payment.paid_at >= since)):
        key = (p.paid_at.astimezone(UTC).date(), p.product_key, p.currency or "?")
        r = revenue.setdefault(key, {"kind": p.kind, "payments": 0, "gross_minor": 0, "refunded_minor": 0, "disputes": 0,
                                     "settled_usd_cents": 0, "refunded_usd_cents": 0, "fees_usd_cents": 0, "unsettled": 0})
        r["payments"] += 1
        r["gross_minor"] += p.amount_minor or 0
        r["refunded_minor"] += p.refunded_amount_minor or 0
        r["disputes"] += int(p.id in disputed)
        if p.settlement_currency not in (None, "USD") or p.settlement_amount_minor is None:
            r["unsettled"] += 1
            continue
        settled, refunded, fees = net_revenue_usd_cents(config, p, p.id in disputed)
        r["settled_usd_cents"] += settled
        r["refunded_usd_cents"] += refunded
        r["fees_usd_cents"] += fees

    await db.execute(delete(DailyLlmCost).where(DailyLlmCost.day >= first))
    await db.execute(delete(DailyRevenue).where(DailyRevenue.day >= first))
    if llm:
        await db.execute(insert(DailyLlmCost), [
            {"day": d, "stage": st, "model": m, "entitlement": e, "calls": v[0], "failed": v[1], "input_tokens": v[2],
             "output_tokens": v[3], "cost_usd": v[4], "wasted_usd": v[5], "unpriced_calls": v[6]}
            for (d, st, m, e), v in llm.items()])
    if revenue:
        await db.execute(insert(DailyRevenue), [
            {"day": d, "product_key": k, "currency": c, **v} for (d, k, c), v in revenue.items()])
    for name in ("llm_costs", "revenue"):
        await db.execute(pg_insert(AggregateRun).values(name=name, refreshed_at=now, days=days)
                         .on_conflict_do_update(index_elements=[AggregateRun.name],
                                                set_={"refreshed_at": now, "days": days}))
    await db.commit()
    return {"llm_rows": len(llm), "revenue_rows": len(revenue), "from": first.isoformat()}
