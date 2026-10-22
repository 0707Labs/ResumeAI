"""What /admin/integrations shows: each connected service's configuration state, recent
activity from our own tables, and an on-demand health check.

Secret values never leave this module. A secret is reported as set or not set; a
superadmin (secrets.hint) also sees its last 4 characters, and only for values long
enough that 4 characters give nothing away. Database URLs are never hinted. Health
checks run here, against read-only endpoints, and store a status plus a short error code
(an HTTP status or an exception class name), never a provider's message.

Checks are in CHECKS so tests can swap them for fakes.
"""

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit

import anthropic
import httpx2
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.mailer import sigv4_headers
from app.auth.oauth import redirect_uri
from app.config import get_settings
from app.db.models import IntegrationCheck, LlmUsage, ProcessedWebhookEvent
from app.llm.client import MODEL, _workspace_header

Status = Literal["healthy", "degraded", "failing", "not_configured"]
NAMES = ("anthropic", "database", "dodo", "email", "google", "github", "slack", "error_monitoring", "analytics")
HTTP_TIMEOUT = 10.0
MIN_HINT_LENGTH = 16


@dataclass
class CheckResult:
    status: Status
    error_code: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _secret(name: str, value: str, *, hint_allowed: bool, hintable: bool = True) -> dict[str, Any]:
    value = value or ""
    hint = ("…" + value[-4:]) if hint_allowed and hintable and len(value) >= MIN_HINT_LENGTH else None
    return {"name": name, "set": bool(value), "hint": hint}


def secrets(name: str, *, hint_allowed: bool) -> list[dict[str, Any]]:
    s = get_settings()
    env = os.environ.get
    table: dict[str, list[tuple[str, str, bool]]] = {
        "anthropic": [("ANTHROPIC_API_KEY", env("ANTHROPIC_API_KEY", ""), True)],
        "database": [("RT_DATABASE_URL", s.database_url, False)],
        "dodo": [("DODO_API_KEY", s.dodo_api_key, True), ("DODO_WEBHOOK_SECRET", s.dodo_webhook_secret, True)],
        "email": [("AWS_ACCESS_KEY_ID", s.aws_access_key_id, True), ("AWS_SECRET_ACCESS_KEY", s.aws_secret_access_key, True)],
        "google": [("GOOGLE_CLIENT_SECRET", s.google_client_secret, True)],
        "github": [("GITHUB_CLIENT_SECRET", s.github_client_secret, True)],
        "slack": [("RT_SLACK_WEBHOOK_URL", s.slack_webhook_url, False)],
    }
    return [_secret(n, v, hint_allowed=hint_allowed, hintable=h) for n, v, h in table.get(name, [])]


def configured(name: str) -> bool:
    s = get_settings()
    return {
        "anthropic": s.llm_configured,
        "database": bool(s.database_url),
        "dodo": bool(s.dodo_api_key and s.dodo_webhook_secret),
        "email": s.mailer == "outbox" or bool(s.mail_from and s.aws_access_key_id and s.aws_secret_access_key),
        "google": bool(s.google_client_id and s.google_client_secret),
        "github": bool(s.github_client_id and s.github_client_secret),
        "slack": s.slack_webhook_url.startswith("https://hooks.slack.com/"),
    }.get(name, False)


# --- what each card shows (no network) ---------------------------------------------------------


async def facts(db: AsyncSession, name: str, now: datetime) -> dict[str, Any]:
    """Non-secret details for one card, from settings and our own tables."""
    s = get_settings()
    day = now - timedelta(days=1)
    if name == "anthropic":
        from app.admin import settings as runtime

        models = sorted(set(await db.scalars(select(LlmUsage.model).where(LlmUsage.created_at >= now - timedelta(days=7))
                                             .distinct())) | {MODEL})
        by_status = dict((await db.execute(select(LlmUsage.status, func.count()).where(LlmUsage.created_at >= day)
                                           .group_by(LlmUsage.status))).all())
        last_ok = await db.scalar(select(func.max(LlmUsage.created_at)).where(LlmUsage.status == "ok"))
        last_bad = (await db.execute(select(LlmUsage.created_at, LlmUsage.status, LlmUsage.error_code)
                                     .where(LlmUsage.status != "ok").order_by(LlmUsage.created_at.desc()).limit(1))).first()
        configured_steps = (await runtime.read_all(db)).values.model_dump(mode="json")["llm_models"]
        return {"default_model": MODEL, "models_in_use_7d": models, "step_models": configured_steps,
                "calls_24h": sum(by_status.values()), "rate_limited_24h": by_status.get("rate_limited", 0),
                "errors_24h": by_status.get("error", 0), "last_success_at": last_ok,
                "last_error": ({"at": last_bad[0], "status": last_bad[1], "code": last_bad[2]} if last_bad else None)}
    if name == "database":
        url = urlsplit(s.database_url.replace("+psycopg", ""))
        return {"host": url.hostname or "local socket", "database": (url.path or "/").lstrip("/") or None}
    if name == "dodo":
        last = await db.scalar(select(func.max(ProcessedWebhookEvent.received_at)))
        failing = await db.scalar(select(func.count()).select_from(ProcessedWebhookEvent)
                                  .where(ProcessedWebhookEvent.processed_at.is_(None)))
        processed = await db.scalar(select(func.count()).select_from(ProcessedWebhookEvent)
                                    .where(ProcessedWebhookEvent.received_at >= day))
        return {"mode": s.dodo_environment, "business_id_set": bool(s.dodo_business_id),
                "webhook_endpoint": f"{s.public_url}/api/billing/webhooks/dodo", "last_event_at": last,
                "failing_events": int(failing or 0), "events_24h": int(processed or 0)}
    if name == "email":
        return {"provider": s.mailer, "sender": s.mail_from or None,
                "region": s.ses_region if s.mailer == "ses" else None,
                "note": "Development outbox: mail is written to backend/.dev-outbox, not sent." if s.mailer == "outbox" else None}
    if name in ("google", "github"):
        client_id = s.google_client_id if name == "google" else s.github_client_id
        return {"client_id_set": bool(client_id), "redirect_uri": redirect_uri(name)}  # type: ignore[arg-type]
    if name == "slack":
        return {"used_for": "Claude budget alerts (python -m app.billing.cli budget-check)"}
    if name == "error_monitoring":
        return {"note": "No error monitoring is connected. Server errors go to the process log."}
    if name == "analytics":
        return {"note": "No analytics by design: only cookie-free daily counts (landing views, parse results)."}
    return {}


# --- health checks (network, read-only) ---------------------------------------------------------


def _status_code(exc: Exception) -> str:
    code = getattr(exc, "status_code", None)
    return f"http_{code}" if code else exc.__class__.__name__[:120]


async def check_anthropic(db: AsyncSession) -> CheckResult:
    if not get_settings().llm_configured:
        return CheckResult("not_configured")
    client = anthropic.AsyncAnthropic(default_headers=_workspace_header(), timeout=HTTP_TIMEOUT, max_retries=0)
    try:
        model = await client.models.retrieve(MODEL)  # free; proves the key and the model
    except anthropic.RateLimitError as exc:
        return CheckResult("degraded", _status_code(exc))
    except anthropic.APIError as exc:
        return CheckResult("failing", _status_code(exc))
    finally:
        await client.close()
    return CheckResult("healthy", detail={"model": model.id})


async def check_database(db: AsyncSession) -> CheckResult:
    row = (await db.execute(text("SELECT current_setting('server_version'), pg_database_size(current_database()),"
                                 " (SELECT version_num FROM alembic_version LIMIT 1)"))).one()
    return CheckResult("healthy", detail={"server_version": row[0], "size_mb": round(row[1] / 1_048_576, 1),
                                          "migration": row[2]})


async def check_dodo(db: AsyncSession) -> CheckResult:
    if not configured("dodo"):
        return CheckResult("not_configured")
    from dodopayments import APIError, AsyncDodoPayments

    from app.billing.providers.dodo import SDK_ENVIRONMENTS

    s = get_settings()
    if s.dodo_environment not in SDK_ENVIRONMENTS:
        return CheckResult("failing", "bad_environment")
    client = AsyncDodoPayments(bearer_token=s.dodo_api_key, environment=SDK_ENVIRONMENTS[s.dodo_environment],
                               base_url=None, timeout=HTTP_TIMEOUT, max_retries=0)
    try:
        await client.products.list(page_size=1)  # read-only
    except APIError as exc:
        return CheckResult("failing", _status_code(exc))
    finally:
        await client.close()
    failing = await db.scalar(select(func.count()).select_from(ProcessedWebhookEvent)
                              .where(ProcessedWebhookEvent.processed_at.is_(None)))
    return CheckResult("degraded" if failing else "healthy", "webhook_failures" if failing else None,
                       {"mode": s.dodo_environment})


_ses_transport: httpx2.AsyncBaseTransport | None = None  # tests inject a mock


async def check_email(db: AsyncSession) -> CheckResult:
    s = get_settings()
    if s.mailer == "outbox":
        return CheckResult("degraded", "dev_outbox", {"provider": "outbox"})
    if not configured("email"):
        return CheckResult("not_configured")
    url = f"https://email.{s.ses_region}.amazonaws.com/v2/email/account"
    headers = {"x-amz-security-token": s.aws_session_token} if s.aws_session_token else {}
    headers = sigv4_headers("GET", url, b"", headers, key_id=s.aws_access_key_id, secret=s.aws_secret_access_key,
                            region=s.ses_region, service="ses", now=datetime.now(UTC))
    try:
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT, transport=_ses_transport) as http:
            res = await http.get(url, headers=headers)
    except httpx2.HTTPError as exc:
        return CheckResult("failing", exc.__class__.__name__)
    if res.status_code != 200:
        return CheckResult("failing", f"http_{res.status_code}")
    body = res.json()
    quota = body.get("SendQuota") or {}
    detail = {"sending_enabled": body.get("SendingEnabled"), "production_access": body.get("ProductionAccessEnabled"),
              "sent_24h": quota.get("SentLast24Hours"), "max_24h": quota.get("Max24HourSend")}
    ok = body.get("SendingEnabled") and body.get("ProductionAccessEnabled")
    return CheckResult("healthy" if ok else "degraded", None if ok else "ses_sandbox_or_paused", detail)


async def check_config_only(name: str) -> CheckResult:
    """OAuth and Slack: nothing to call without side effects; check the configuration."""
    return CheckResult("healthy" if configured(name) else "not_configured")


CHECKS: dict[str, Callable[[AsyncSession], Awaitable[CheckResult]]] = {
    "anthropic": check_anthropic, "database": check_database, "dodo": check_dodo, "email": check_email,
    "google": lambda db: check_config_only("google"), "github": lambda db: check_config_only("github"),
    "slack": lambda db: check_config_only("slack"),
}


async def run_check(db: AsyncSession, name: str, actor_id: Any, now: datetime | None = None) -> IntegrationCheck:
    """Run one check and store the result (the caller audits and commits)."""
    now = now or datetime.now(UTC)
    try:
        result = await CHECKS[name](db)
    except Exception as exc:  # noqa: BLE001 - a broken check is a failing integration
        result = CheckResult("failing", exc.__class__.__name__[:120])
    values = {"status": result.status, "checked_at": now, "error_code": result.error_code, "detail": result.detail,
              "checked_by": actor_id}
    stmt = insert(IntegrationCheck).values(name=name, last_ok_at=now if result.status == "healthy" else None, **values)
    await db.execute(stmt.on_conflict_do_update(index_elements=[IntegrationCheck.name], set_={
        **values, "last_ok_at": func.coalesce(stmt.excluded.last_ok_at, IntegrationCheck.last_ok_at)}))
    return await db.get(IntegrationCheck, name, populate_existing=True)
