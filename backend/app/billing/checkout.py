"""Starting a checkout. Who pays comes from the session and what is sold comes from
the catalog; the request only names a product key. Nothing here grants anything:
credits and passes come only from verified webhooks.
"""

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.config import BillingConfig, Product
from app.billing.providers.base import Buyer, PaymentError, PaymentProvider, ProductUnavailable
from app.db.models import BillingCustomer, Payment, User

# Dodo checkout sessions expire after 24 hours; reuse a stored URL only well before that.
SESSION_TTL = timedelta(hours=24)
REUSE_MARGIN = timedelta(minutes=30)


class CheckoutError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StartedCheckout:
    payment_id: uuid.UUID
    checkout_url: str


def snapshot(config: BillingConfig, product: Product) -> dict:
    """What this purchase promises, frozen at checkout."""
    return {
        "catalog_version": config.version,
        "name": product.name,
        "credits": product.credits,
        "pass_days": product.pass_days,
        "fair_use_cap": product.fair_use_cap,
        "interval": product.interval,
        "display_prices": dict(product.prices),
    }


async def start_checkout(db: AsyncSession, provider: PaymentProvider, config: BillingConfig, user: User, *,
                         product_key: str, idempotency_key: str | None, return_base: str) -> StartedCheckout:
    product = config.product(product_key)
    if product is None or not product.dodo_product_id.for_mode(provider.mode):
        raise CheckoutError("product_unavailable")
    key = idempotency_key or f"auto:{uuid.uuid4()}"
    now = datetime.now(UTC)
    # Read before any commit or rollback expires the ORM object.
    buyer = Buyer(user_id=user.id, email=user.email, name=user.name)

    inserted = await db.scalar(
        insert(Payment).values(
            user_id=buyer.user_id, provider=provider.name, mode=provider.mode, product_key=product.key,
            kind=product.kind, snapshot=snapshot(config, product), idempotency_key=key,
        ).on_conflict_do_nothing(index_elements=["user_id", "idempotency_key"]).returning(Payment.id)
    )
    if inserted is None:  # this key was used before: same click, retried
        await db.rollback()
        existing = await db.scalar(
            select(Payment).where(Payment.user_id == buyer.user_id, Payment.idempotency_key == key)
        )
        if existing.product_key != product.key:
            raise CheckoutError("idempotency_key_reused")
        if (existing.status == "created" and existing.checkout_url and existing.checkout_expires_at
                and existing.checkout_expires_at - REUSE_MARGIN > now):
            return StartedCheckout(existing.id, existing.checkout_url)
        raise CheckoutError("checkout_in_progress" if existing.status == "created" else "checkout_closed")
    await db.commit()  # the row exists before the provider session does

    customer_id = await db.scalar(
        select(BillingCustomer.provider_customer_id).where(
            BillingCustomer.user_id == buyer.user_id, BillingCustomer.provider == provider.name
        )
    )
    buyer = dataclasses.replace(buyer, provider_customer_id=customer_id)
    try:
        session = await provider.create_checkout(
            buyer, product, return_url=f"{return_base}/billing/success?payment={inserted}",
            cancel_url=f"{return_base}/pricing",
        )
    except (PaymentError, ProductUnavailable) as exc:
        await db.execute(update(Payment).where(Payment.id == inserted)
                         .values(status="checkout_failed", updated_at=now))
        await db.commit()
        raise CheckoutError("checkout_failed") from exc

    await db.execute(
        update(Payment).where(Payment.id == inserted).values(
            provider_checkout_id=session.provider_checkout_id, checkout_url=session.url,
            checkout_expires_at=now + SESSION_TTL, updated_at=now,
        )
    )
    await db.commit()
    return StartedCheckout(inserted, session.url)
