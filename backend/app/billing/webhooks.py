"""Processing one verified webhook delivery exactly once.

The delivery id goes into processed_webhook_events in the same transaction as the
event's effects. A concurrent duplicate waits on that row, then sees it processed.
On any error the transaction rolls back, a failure count is recorded separately,
and the caller answers 5xx so the provider retries. Everything is a few DB
statements, well inside Dodo's 30-second timeout, so the work is done inline
rather than queued.
"""

import logging
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import null, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.config import BillingConfig
from app.billing.events import apply_event
from app.billing.providers.base import PaymentProvider, WebhookEvent
from app.db.models import ProcessedWebhookEvent

log = logging.getLogger("app.billing")

Result = Literal["processed", "ignored", "flagged", "duplicate"]


async def process_webhook(db: AsyncSession, provider: PaymentProvider, config: BillingConfig,
                          event: WebhookEvent) -> Result:
    try:
        inserted = await db.scalar(
            insert(ProcessedWebhookEvent).values(
                provider=provider.name, event_id=event.event_id, event_type=event.type,
                occurred_at=event.occurred_at,
            ).on_conflict_do_nothing().returning(ProcessedWebhookEvent.event_id)
        )
        if inserted is None:
            row = await db.scalar(
                select(ProcessedWebhookEvent).where(
                    ProcessedWebhookEvent.provider == provider.name,
                    ProcessedWebhookEvent.event_id == event.event_id,
                ).with_for_update()
            )
            if row.processed_at is not None:
                await db.rollback()
                return "duplicate"
        outcome = await apply_event(db, provider, config, event)
        await db.execute(
            update(ProcessedWebhookEvent).where(
                ProcessedWebhookEvent.provider == provider.name,
                ProcessedWebhookEvent.event_id == event.event_id,
            ).values(processed_at=datetime.now(UTC), outcome=outcome, payload=null())  # SQL NULL, not JSON null
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        failures = await _record_failure(db, provider.name, event, exc)
        if failures == config.alerts.webhook_failures:
            log.critical("ALERT webhook %s %s has failed %d times; the purchase may not be granted",
                         event.type, event.event_id, failures)
        raise
    log.info("webhook %s %s: %s", event.type, event.event_id, outcome)
    return outcome


async def _record_failure(db: AsyncSession, provider: str, event: WebhookEvent, exc: Exception) -> int:
    """Count the failure (separate transaction); returns the failure count so far, 0 if unknown."""
    error = exc.__class__.__name__  # never the message: it may quote payload data
    failures = 0
    try:
        failures = await db.scalar(
            insert(ProcessedWebhookEvent).values(
                provider=provider, event_id=event.event_id, event_type=event.type,
                occurred_at=event.occurred_at, failures=1, last_error=error, payload=dict(event.data),
            ).on_conflict_do_update(
                index_elements=["provider", "event_id"],
                # The verified data, kept while failing so staff can replay it (cleared on success).
                set_={"failures": ProcessedWebhookEvent.failures + 1, "last_error": error,
                      "payload": dict(event.data)},
            ).returning(ProcessedWebhookEvent.failures)
        ) or 0
        await db.commit()
    except Exception:  # noqa: BLE001 - the original error is what matters
        await db.rollback()
    log.error("webhook %s %s failed: %s", event.type, event.event_id, error)
    return failures


class NotReplayable(Exception):
    """The delivery is processed already, or has no stored payload."""


async def replay(db: AsyncSession, provider: PaymentProvider, config: BillingConfig, event_id: str) -> Result:
    """Run a failed delivery again from its stored, already-verified data. Idempotent:
    the same path as a live delivery, so a processed event is never applied twice."""
    row = await db.scalar(select(ProcessedWebhookEvent).where(
        ProcessedWebhookEvent.provider == provider.name, ProcessedWebhookEvent.event_id == event_id))
    if row is None or row.processed_at is not None or row.payload is None:
        raise NotReplayable(event_id)
    event = WebhookEvent(event_id=row.event_id, type=row.event_type, occurred_at=row.occurred_at, data=row.payload)
    await db.rollback()  # release the read; process_webhook takes its own lock
    return await process_webhook(db, provider, config, event)
