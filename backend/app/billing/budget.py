"""Claude spend budgets: the kill switch and the 50/80/100% alerts.

Spend is the sum of llm_usage.cost_usd since 00:00 UTC (daily) and since the 1st of the
month (monthly). Budgets and the kill switch are runtime settings (app.admin.settings:
daily_budget_usd, monthly_budget_usd, budget_kill_switch), defaulting to billing.toml.

- `pause_reason()` is checked when an analysis starts: staff paused analyses by hand
  (analyses_paused), or the kill switch is on and a budget is used up. New analyses wait;
  ones already running finish. It resumes on its own when the day or month turns over,
  or when staff raise the budget.
- `check_and_alert()` runs from cron (`python -m app.billing.cli budget-check`, every few
  minutes). Each threshold alerts once per period (budget_alerts): email to active admins
  and superadmins, and Slack when RT_SLACK_WEBHOOK_URL is set. Alerts carry amounts only.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import httpx2
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as runtime
from app.auth.mailer import Mail, MailerError, get_mailer
from app.billing.analyses import day_start, month_start
from app.config import get_settings
from app.db.models import BudgetAlert, LlmUsage, User
from app.db.rls import service_scope

log = logging.getLogger("app.billing")
THRESHOLDS = (50, 80, 100)
SLACK_PREFIX = "https://hooks.slack.com/"
_slack_transport: httpx2.AsyncBaseTransport | None = None  # tests inject a mock


def set_slack_transport(transport: httpx2.AsyncBaseTransport | None) -> None:
    global _slack_transport
    _slack_transport = transport


@dataclass(frozen=True)
class Spend:
    today_usd: Decimal
    month_usd: Decimal
    daily_budget_usd: Decimal
    monthly_budget_usd: Decimal
    kill_switch: bool
    paused_by_hand: bool

    @property
    def over(self) -> Literal["daily_budget", "monthly_budget"] | None:
        if self.today_usd >= self.daily_budget_usd:
            return "daily_budget"
        if self.month_usd >= self.monthly_budget_usd:
            return "monthly_budget"
        return None


async def spend(db: AsyncSession, now: datetime | None = None) -> Spend:
    now = now or datetime.now(UTC)
    async with service_scope(db):  # llm_usage is staff-only
        today, month = (await db.execute(select(
            func.coalesce(func.sum(LlmUsage.cost_usd).filter(LlmUsage.created_at >= day_start(now)), 0),
            func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(LlmUsage.created_at >= month_start(now)))).one()
    values = (await runtime.read_all(db)).values
    return Spend(Decimal(today), Decimal(month), Decimal(str(values.daily_budget_usd)),
                 Decimal(str(values.monthly_budget_usd)), values.budget_kill_switch, values.analyses_paused)


async def pause_reason(db: AsyncSession, now: datetime | None = None) -> str | None:
    """Why new analyses can't start right now, or None."""
    s = await spend(db, now)
    if s.paused_by_hand:
        return "manual"
    return s.over if s.kill_switch else None


async def check_and_alert(db: AsyncSession, now: datetime | None = None) -> list[tuple[str, int]]:
    """Send each newly crossed threshold once. Returns the (period, threshold) pairs sent."""
    now = now or datetime.now(UTC)
    s = await spend(db, now)
    sent = []
    for period, used, budget in ((f"day:{now:%Y-%m-%d}", s.today_usd, s.daily_budget_usd),
                                 (f"month:{now:%Y-%m}", s.month_usd, s.monthly_budget_usd)):
        pct = used / budget * 100 if budget > 0 else Decimal(0)
        for threshold in THRESHOLDS:
            if pct < threshold:
                continue
            claimed = await db.scalar(insert(BudgetAlert).values(
                period=period, threshold=threshold, spend_usd=used, budget_usd=budget)
                .on_conflict_do_nothing().returning(BudgetAlert.threshold))
            await db.commit()  # claimed before sending: a concurrent run can't send it twice
            if claimed is None:
                continue
            await _notify(db, period, threshold, used, budget, s.kill_switch)
            sent.append((period, threshold))
    return sent


def _text(period: str, threshold: int, used: Decimal, budget: Decimal, kill_switch: bool) -> str:
    what = "Today's" if period.startswith("day:") else "This month's"
    line = f"{what} Claude spend is ${used:.2f} of ${budget:.2f} ({threshold}% reached)."
    if threshold >= 100:
        line += " New analyses are paused until it resets." if kill_switch else " The kill switch is off, so analyses continue."
    return line


async def _notify(db: AsyncSession, period: str, threshold: int, used: Decimal, budget: Decimal, kill: bool) -> None:
    message = _text(period, threshold, used, budget, kill)
    log.warning("budget alert %s %s%%: %s", period, threshold, message)
    staff = list(await db.scalars(select(User.email).where(
        User.role.in_(("admin", "superadmin")), User.status == "active", User.deleted_at.is_(None))))
    base = get_settings().public_url
    mailer = get_mailer()
    for email in staff:
        try:
            await run_in_threadpool(mailer.send, Mail(
                to=email, subject=f"Claude spend at {threshold}% of budget", link=f"{base}/admin/costs",
                lines=(message,), button="Open costs", footer="Sent to Resume Tailor admins.", footer_in_text=True))
        except MailerError as exc:
            log.warning("budget alert email failed: %s", exc.reason)
    url = get_settings().slack_webhook_url
    if url.startswith(SLACK_PREFIX):
        try:
            async with httpx2.AsyncClient(timeout=5, transport=_slack_transport, follow_redirects=False) as http:
                await http.post(url, content=json.dumps({"text": f":warning: {message} {base}/admin/costs"}),
                                headers={"Content-Type": "application/json"})
        except httpx2.HTTPError as exc:
            log.warning("budget alert to Slack failed: %s", exc.__class__.__name__)
