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

from sqlalchemy import select, update
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
            ).values(processed_at=datetime.now(UTC), outcome=outcome)
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        await _record_failure(db, provider.name, event, exc)
        raise
    log.info("webhook %s %s: %s", event.type, event.event_id, outcome)
    return outcome


async def _record_failure(db: AsyncSession, provider: str, event: WebhookEvent, exc: Exception) -> None:
    error = exc.__class__.__name__  # never the message: it may quote payload data
    try:
        await db.execute(
            insert(ProcessedWebhookEvent).values(
                provider=provider, event_id=event.event_id, event_type=event.type,
                occurred_at=event.occurred_at, failures=1, last_error=error,
            ).on_conflict_do_update(
                index_elements=["provider", "event_id"],
                set_={"failures": ProcessedWebhookEvent.failures + 1, "last_error": error},
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - the original error is what matters
        await db.rollback()
    log.error("webhook %s %s failed: %s", event.type, event.event_id, error)
