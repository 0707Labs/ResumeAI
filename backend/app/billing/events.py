"""What a verified webhook means for our records. The only code that grants or takes
back credits and passes because of a payment.

Runs inside the webhook's transaction (app/billing/webhooks.py), which also marks
the delivery processed, so effects and the processed mark commit together. Every
effect is also idempotent on its own (ledger keys, conditional status updates), so
even a delivery that slipped past the event table would not double-grant.

Dodo event names and payload fields: docs.dodopayments.com/developer-resources/webhooks
and the SDK's types (Payment, Refund, Dispute, Subscription), read 2026-10-21.

Refund and dispute policy:
- A full refund, a lost dispute or an accepted dispute takes back the pack's credits
  (whatever is still owed after earlier refunds) or revokes the pass.
- A partial refund of a pack takes back credits in proportion to the amount refunded,
  rounded down; if the amounts can't be compared it is flagged instead.
- Never below zero: credits already spent are flagged for admin review
  ('credits_already_used'), never left as a negative balance.
"""

import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import ledger
from app.billing.config import BillingConfig
from app.billing.providers.base import PaymentProvider, WebhookEvent
from app.db.models import BillingCustomer, BillingReview, Payment, Subscription, User

log = logging.getLogger("app.billing")

Outcome = Literal["processed", "ignored", "flagged"]


class RetryLater(Exception):
    """Not processable yet (e.g. a subscription event before we know its buyer).
    The webhook answers 5xx so the provider delivers it again later."""


def _now() -> datetime:
    return datetime.now(UTC)


async def flag(db: AsyncSession, kind: str, dedupe_key: str, *, payment_id: uuid.UUID | None = None,
               **detail: Any) -> None:
    await db.execute(
        insert(BillingReview).values(kind=kind, dedupe_key=dedupe_key, payment_id=payment_id, detail=detail)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    log.warning("billing review flagged: %s %s", kind, dedupe_key)


async def _payment_by(db: AsyncSession, provider: str, **where: str | None) -> Payment | None:
    (column, value), = where.items()
    if not value:
        return None
    return await db.scalar(
        select(Payment).where(Payment.provider == provider, getattr(Payment, column) == value).with_for_update()
    )


async def apply_event(db: AsyncSession, provider: PaymentProvider, config: BillingConfig,
                      event: WebhookEvent) -> Outcome:
    handler = HANDLERS.get(event.type)
    if handler is None:
        return "ignored"  # unknown or uninteresting types are acknowledged and recorded
    return await handler(db, provider, config, event)


# --- payments ----------------------------------------------------------------------------


async def payment_succeeded(db, provider, config, event) -> Outcome:
    data = event.data
    payment = await _payment_by(db, provider.name, provider_checkout_id=data.get("checkout_session_id"))
    if payment is None:
        if data.get("subscription_id"):
            return "ignored"  # a renewal charge: subscription.renewed is the signal for those
        await flag(db, "unknown_payment", f"unknown_payment:{data.get('payment_id')}",
                   provider_payment_id=data.get("payment_id"))
        return "flagged"

    provider_payment_id = data.get("payment_id")
    if payment.status in ("paid", "partially_refunded", "refunded", "disputed"):
        if payment.provider_payment_id == provider_payment_id:
            return "ignored"  # already applied (a second delivery under a new id)
        await flag(db, "payment_mismatch", f"second_payment:{provider_payment_id}", payment_id=payment.id,
                   reason="checkout paid twice", provider_payment_id=provider_payment_id)
        return "flagged"

    if problem := _mismatch(payment, data):
        await flag(db, "payment_mismatch", f"mismatch:{provider_payment_id}", payment_id=payment.id,
                   reason=problem, provider_payment_id=provider_payment_id)
        return "flagged"

    payment.status = "paid"
    payment.provider_payment_id = provider_payment_id
    payment.provider_subscription_id = data.get("subscription_id")
    payment.currency = data.get("currency")
    payment.amount_minor = data.get("total_amount")
    payment.tax_minor = data.get("tax")
    payment.settlement_amount_minor = data.get("settlement_amount")
    payment.settlement_currency = data.get("settlement_currency")
    payment.settlement_tax_minor = data.get("settlement_tax")
    payment.paid_at = _now()
    payment.updated_at = _now()
    await db.flush()

    customer_id = (data.get("customer") or {}).get("customer_id")
    if customer_id and payment.user_id:
        await db.execute(
            insert(BillingCustomer).values(user_id=payment.user_id, provider=provider.name,
                                           provider_customer_id=customer_id)
            .on_conflict_do_nothing()
        )

    if payment.user_id is None:
        await flag(db, "user_missing", f"user_missing:{payment.id}", payment_id=payment.id)
        return "flagged"
    snap = payment.snapshot
    if payment.kind == "credit_pack":
        await ledger.grant(db, payment.user_id, snap["credits"], reason="purchase",
                           idempotency_key=f"purchase:{payment.id}", reference_id=provider_payment_id)
    elif payment.kind == "pass":
        await ledger.grant_pass(db, payment.user_id, product_key=payment.product_key, days=snap["pass_days"],
                                analyses_cap=snap["fair_use_cap"], reference_id=provider_payment_id)
    # Pro access comes from the subscription row (subscription.* events), not from here.
    return "processed"


def _mismatch(payment: Payment, data: Mapping[str, Any]) -> str | None:
    metadata = data.get("metadata") or {}
    if "user_id" in metadata and metadata["user_id"] != str(payment.user_id):
        return "metadata user_id differs from the checkout's user"
    if "product_key" in metadata and metadata["product_key"] != payment.product_key:
        return "metadata product_key differs from the checkout's product"
    expected = payment.snapshot.get("provider_product_id")
    cart = data.get("product_cart")
    if payment.kind != "subscription" and expected and cart is not None:
        if [(i.get("product_id"), i.get("quantity")) for i in cart] != [(expected, 1)]:
            return "product_cart is not exactly one of the purchased product"
    return None


async def payment_progress(db, provider, config, event) -> Outcome:
    """payment.processing / payment.failed / payment.cancelled: status only, never after paid."""
    new_status = {"payment.processing": "pending", "payment.failed": "failed",
                  "payment.cancelled": "cancelled"}[event.type]
    session_id = event.data.get("checkout_session_id")
    if not session_id:
        return "ignored"  # e.g. a failed renewal; subscription events carry that state
    result = await db.execute(
        update(Payment).where(Payment.provider == provider.name, Payment.provider_checkout_id == session_id,
                              Payment.status.in_(("created", "pending", "failed", "cancelled")))
        .values(status=new_status, updated_at=_now())
    )
    return "processed" if result.rowcount else "ignored"


# --- refunds and disputes -------------------------------------------------------------------


async def _take_back(db: AsyncSession, payment: Payment, credits: int, key: str, cause: str) -> None:
    """Reverse up to `credits` of a pack, at most once per key; flag what was already spent."""
    credits = min(credits, payment.snapshot["credits"] - payment.credits_reversed)
    if credits <= 0 or payment.user_id is None:
        return
    reversal = await ledger.reverse_purchase(db, payment.user_id, credits, idempotency_key=key,
                                             reference_id=payment.provider_payment_id, note=cause)
    if reversal.posted.applied:
        payment.credits_reversed += credits
    if reversal.shortfall:
        await flag(db, "credits_already_used", f"used:{key}", payment_id=payment.id, cause=cause,
                   requested=credits, shortfall=reversal.shortfall)


async def _reverse_in_full(db: AsyncSession, payment: Payment, key: str, cause: str) -> None:
    if payment.kind == "credit_pack":
        await _take_back(db, payment, payment.snapshot["credits"], key, cause)
    elif payment.kind == "pass":
        await ledger.revoke_pass(db, payment.provider_payment_id)


async def refund_succeeded(db, provider, config, event) -> Outcome:
    data = event.data
    refund_id = data.get("refund_id")
    payment = await _payment_by(db, provider.name, provider_payment_id=data.get("payment_id"))
    if payment is None:
        await flag(db, "unknown_payment", f"unknown_refund:{refund_id}", refund_id=refund_id,
                   provider_payment_id=data.get("payment_id"))
        return "flagged"
    if refund_id in payment.refund_ids:
        return "ignored"  # this refund was already applied (a redelivery under a new id)
    payment.refund_ids = [*payment.refund_ids, refund_id]
    key = f"refund:{refund_id}"
    outcome: Outcome = "processed"
    amount, currency = data.get("amount"), data.get("currency")
    if not data.get("is_partial"):
        await _reverse_in_full(db, payment, key, "refund")
        payment.status = "refunded"
        payment.refunded_amount_minor = payment.amount_minor or 0
    else:
        if payment.status != "refunded":
            payment.status = "partially_refunded"
        if amount and currency and currency == payment.currency:
            payment.refunded_amount_minor = min(payment.amount_minor or amount,
                                                payment.refunded_amount_minor + amount)
        if (payment.kind == "credit_pack" and amount and payment.amount_minor
                and currency and currency == payment.currency):
            credits = payment.snapshot["credits"] * amount // payment.amount_minor
            await _take_back(db, payment, credits, key, "partial refund")
        else:
            await flag(db, "partial_refund", f"partial:{refund_id}", payment_id=payment.id, refund_id=refund_id,
                       amount=amount, currency=currency)
            outcome = "flagged"
    payment.updated_at = _now()
    return outcome


async def dispute_changed(db, provider, config, event) -> Outcome:
    data = event.data
    dispute_id = data.get("dispute_id")
    payment = await _payment_by(db, provider.name, provider_payment_id=data.get("payment_id"))
    if payment is None:
        await flag(db, "unknown_payment", f"unknown_dispute:{dispute_id}:{event.type}", dispute_id=dispute_id,
                   provider_payment_id=data.get("payment_id"))
        return "flagged"
    if event.type == "dispute.opened":
        if payment.status in ("paid", "partially_refunded"):
            payment.status = "disputed"
        await flag(db, "dispute_opened", f"dispute:{dispute_id}", payment_id=payment.id, dispute_id=dispute_id,
                   amount=data.get("amount"), currency=data.get("currency"))
        payment.updated_at = _now()
        return "flagged"
    if event.type in ("dispute.lost", "dispute.accepted"):
        # Visa RDR refunds automatically and reports it as dispute.lost (is_resolved_by_rdr).
        await _reverse_in_full(db, payment, f"dispute:{dispute_id}", "lost dispute")
        payment.status = "refunded"
    elif event.type in ("dispute.won", "dispute.cancelled", "dispute.expired") and payment.status == "disputed":
        payment.status = "paid"
    payment.updated_at = _now()
    return "processed"


# --- subscriptions ----------------------------------------------------------------------------


async def _subscriber(db: AsyncSession, provider: str, data: Mapping[str, Any]) -> uuid.UUID:
    user_id = (data.get("metadata") or {}).get("user_id")
    if user_id:
        try:
            found = await db.scalar(select(User.id).where(User.id == uuid.UUID(str(user_id))))
        except ValueError:
            found = None
        if found:
            return found
    customer_id = (data.get("customer") or {}).get("customer_id")
    if customer_id:
        found = await db.scalar(select(BillingCustomer.user_id).where(
            BillingCustomer.provider == provider, BillingCustomer.provider_customer_id == customer_id))
        if found:
            return found
    raise RetryLater("subscription buyer not known yet")


def _product_key(config: BillingConfig, mode: str, product_id: str | None) -> str | None:
    for key, product in config.products.items():
        if product.kind == "subscription" and product_id and product.dodo_product_id.for_mode(mode) == product_id:
            return key
    return None


def _ts(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None


async def subscription_changed(db, provider, config, event) -> Outcome:
    data = event.data
    sub_id = data.get("subscription_id")
    product_key = _product_key(config, provider.mode, data.get("product_id"))
    status = data.get("status")
    if not sub_id or product_key is None or status not in (
            "pending", "active", "on_hold", "paused", "cancelled", "failed", "expired", "past_due"):
        return "ignored"
    user_id = await _subscriber(db, provider.name, data)
    values = dict(user_id=user_id, product_key=product_key, status=status,
                  current_period_end=_ts(data.get("next_billing_date")),
                  cancel_at_period_end=bool(data.get("cancel_at_next_billing_date")),
                  last_event_at=event.occurred_at, updated_at=_now())
    written = await db.scalar(
        insert(Subscription).values(provider=provider.name, provider_subscription_id=sub_id, **values)
        .on_conflict_do_update(
            index_elements=["provider", "provider_subscription_id"], set_=values,
            where=Subscription.last_event_at <= event.occurred_at,  # older events don't overwrite newer state
        ).returning(Subscription.id)
    )
    return "processed" if written else "ignored"


HANDLERS = {
    "payment.succeeded": payment_succeeded,
    "payment.processing": payment_progress,
    "payment.failed": payment_progress,
    "payment.cancelled": payment_progress,
    "refund.succeeded": refund_succeeded,
    # refund.failed changes nothing of ours: nothing was taken back before success.
    **{f"dispute.{s}": dispute_changed
       for s in ("opened", "challenged", "accepted", "cancelled", "expired", "won", "lost")},
    **{f"subscription.{s}": subscription_changed
       for s in ("active", "updated", "renewed", "on_hold", "past_due", "paused", "unpaused",
                 "plan_changed", "cancelled", "failed", "expired")},
}
