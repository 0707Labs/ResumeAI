"""Dodo Payments (merchant of record), via the official `dodopayments` SDK.

Docs read 2026-10-21: docs.dodopayments.com (webhooks, checkout sessions, refunds,
customer portal, test mode). Notes on choices:
- The client gets the key, webhook secret and environment explicitly, with
  base_url=None, so the SDK's own DODO_PAYMENTS_* env vars and its live-mode
  default never apply.
- Checkout carries our user_id and product key as metadata. Webhooks are mapped back
  by checkout session id first; Dodo doesn't document that checkout metadata is
  copied onto the payment, so metadata is only a cross-check.
- Refund creation runs with SDK retries off: Dodo has no idempotency key for refunds.
"""

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from dodopayments import APIError, AsyncDodoPayments

from app.billing.config import Product
from app.billing.providers.base import (
    Buyer,
    CheckoutSession,
    InvalidSignature,
    PaymentError,
    ProductUnavailable,
    ProviderNotConfigured,
    RefundResult,
    WebhookEvent,
)

SDK_ENVIRONMENTS = {"test": "test_mode", "live": "live_mode"}
PORTAL_HOSTS = {"test": "https://test.customer.dodopayments.com", "live": "https://customer.dodopayments.com"}
REFUND_STATUSES = ("pending", "review", "succeeded", "failed")


class DodoProvider:
    name = "dodo"

    def __init__(self, *, api_key: str, webhook_secret: str, environment: str, business_id: str = "",
                 client: AsyncDodoPayments | None = None) -> None:
        if environment not in SDK_ENVIRONMENTS:
            raise ProviderNotConfigured("DODO_ENVIRONMENT must be 'test' or 'live'")
        if not api_key or not webhook_secret:
            raise ProviderNotConfigured("DODO_API_KEY and DODO_WEBHOOK_SECRET are required")
        self.mode: Literal["test", "live"] = environment  # type: ignore[assignment]
        self._business_id = business_id
        self._client = client or AsyncDodoPayments(
            bearer_token=api_key,
            webhook_key=webhook_secret,
            environment=SDK_ENVIRONMENTS[environment],  # type: ignore[arg-type]
            base_url=None,
        )

    # --- checkout ------------------------------------------------------------------

    async def create_checkout(self, buyer: Buyer, product: Product, *, return_url: str,
                              cancel_url: str | None = None) -> CheckoutSession:
        product_id = product.dodo_product_id.for_mode(self.mode)
        if not product.enabled or not product_id:
            raise ProductUnavailable(product.key)
        customer: dict[str, Any] = (
            {"customer_id": buyer.provider_customer_id} if buyer.provider_customer_id
            else {"email": buyer.email, **({"name": buyer.name} if buyer.name else {})}
        )
        try:
            session = await self._client.checkout_sessions.create(
                product_cart=[{"product_id": product_id, "quantity": 1}],
                customer=customer,  # type: ignore[arg-type]
                return_url=return_url,
                **({"cancel_url": cancel_url} if cancel_url else {}),
                metadata={"user_id": str(buyer.user_id), "product_key": product.key},
                # No codes exist; an open code box invites coupon hunting.
                feature_flags={"allow_discount_code": False},
            )
        except APIError as exc:
            raise PaymentError(f"checkout failed: {exc.__class__.__name__}") from exc
        if not session.checkout_url:
            raise PaymentError("checkout returned no URL")
        return CheckoutSession(provider_checkout_id=session.session_id, url=session.checkout_url)

    # --- webhooks ------------------------------------------------------------------

    def handle_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        """Standard Webhooks verification by the SDK over the exact raw body (decoded,
        never re-serialized), then a plain-dict parse so unknown event types survive."""
        from standardwebhooks.webhooks import WebhookVerificationError

        lowered = {k.lower(): v for k, v in headers.items()}
        try:
            body = raw_body.decode("utf-8")
            self._client.webhooks.unwrap(body, headers=lowered)
            envelope = json.loads(body)
        except (WebhookVerificationError, ValueError) as exc:
            raise InvalidSignature(exc.__class__.__name__) from exc
        try:
            return WebhookEvent(
                event_id=lowered["webhook-id"],
                type=str(envelope["type"]),
                occurred_at=datetime.fromisoformat(envelope["timestamp"]),
                data=envelope.get("data") or {},
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PaymentError("malformed webhook envelope") from exc

    # --- customer portal -------------------------------------------------------------

    async def get_portal_url(self, buyer: Buyer, *, return_url: str | None = None) -> str | None:
        """A signed-in portal session (valid 24h) when we know the Dodo customer;
        otherwise the static login page, where Dodo emails the buyer a sign-in link."""
        if buyer.provider_customer_id:
            try:
                session = await self._client.customers.customer_portal.create(
                    buyer.provider_customer_id, **({"return_url": return_url} if return_url else {})
                )
            except APIError as exc:
                raise PaymentError(f"portal failed: {exc.__class__.__name__}") from exc
            return session.link
        if self._business_id:
            return f"{PORTAL_HOSTS[self.mode]}/login/{self._business_id}"
        return None

    # --- refunds ---------------------------------------------------------------------

    async def refund(self, payment_id: str, *, reason: str, amount_minor: int | None = None,
                     item_id: str | None = None, metadata: Mapping[str, str] | None = None) -> RefundResult:
        if amount_minor is not None and (amount_minor <= 0 or not item_id):
            raise ValueError("a partial refund needs a positive amount and the item (product) id")
        items = [{"item_id": item_id, "amount": amount_minor}] if amount_minor is not None else None
        try:
            result = await self._client.with_options(max_retries=0).refunds.create(
                payment_id=payment_id,
                reason=reason,
                **({"items": items} if items else {}),  # type: ignore[arg-type]
                **({"metadata": dict(metadata)} if metadata else {}),
            )
        except APIError as exc:
            raise PaymentError(f"refund failed: {exc.__class__.__name__}") from exc
        raw = str(result.status or "")
        status = raw if raw in REFUND_STATUSES else "pending"
        return RefundResult(provider_refund_id=result.refund_id, status=status, raw_status=raw)  # type: ignore[arg-type]
