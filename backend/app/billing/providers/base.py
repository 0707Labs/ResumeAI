"""The PaymentProvider interface. The rest of the app talks only to this, so the
payment provider can be swapped; providers never touch the database.

Amounts are integer minor units. Nothing here grants credits: a provider verifies
and parses; app code decides what a verified event means for the ledger.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from app.billing.config import Product


class PaymentError(Exception):
    """The provider rejected or failed a request."""


class ProviderNotConfigured(PaymentError):
    """Keys or environment are missing or invalid; payments are unavailable."""


class ProductUnavailable(PaymentError):
    """The product is flagged off or has no provider product id in this mode."""


class InvalidSignature(Exception):
    """A webhook failed verification: bad or missing signature, or a stale timestamp."""


@dataclass(frozen=True)
class Buyer:
    """Who is paying, always taken from the signed-in session, never from the request body."""

    user_id: uuid.UUID
    email: str
    name: str | None = None
    provider_customer_id: str | None = None  # learned from an earlier payment


@dataclass(frozen=True)
class CheckoutSession:
    provider_checkout_id: str
    url: str


@dataclass(frozen=True)
class WebhookEvent:
    """A verified webhook. `event_id` is the delivery's unique id, the idempotency key."""

    event_id: str
    type: str
    occurred_at: datetime
    data: Mapping[str, Any]


@dataclass(frozen=True)
class RefundResult:
    """Refunds settle asynchronously; the final state arrives as a webhook."""

    provider_refund_id: str
    status: Literal["pending", "review", "succeeded", "failed"]
    raw_status: str = field(default="", compare=False)


class PaymentProvider(Protocol):
    name: str
    mode: Literal["test", "live"]

    async def create_checkout(self, buyer: Buyer, product: Product, *, return_url: str,
                              cancel_url: str | None = None) -> CheckoutSession: ...

    def handle_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        """Verify the signature over the exact raw bytes, then parse. Raises InvalidSignature."""
        ...

    async def get_portal_url(self, buyer: Buyer, *, return_url: str | None = None) -> str | None: ...

    async def refund(self, payment_id: str, *, reason: str, amount_minor: int | None = None,
                     item_id: str | None = None, metadata: Mapping[str, str] | None = None) -> RefundResult:
        """Full refund when amount_minor is None; otherwise a partial refund of item_id."""
        ...
