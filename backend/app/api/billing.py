"""/api/billing: starting a checkout and receiving the provider's webhooks."""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.billing.checkout import CheckoutError, start_checkout
from app.billing.config import BillingConfig, get_billing_config
from app.billing.providers import PaymentProvider, ProviderNotConfigured, get_payment_provider
from app.billing.providers.base import InvalidSignature, PaymentError
from app.billing.webhooks import process_webhook
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/billing")

ERROR_STATUS = {
    "product_unavailable": 404,
    "idempotency_key_reused": 422,
    "checkout_in_progress": 409,
    "checkout_closed": 409,
    "checkout_failed": 502,
}


def billing_config() -> BillingConfig:
    return get_billing_config()


def payment_provider() -> PaymentProvider:
    try:
        return get_payment_provider()
    except ProviderNotConfigured:
        raise HTTPException(status_code=503, detail="payments_unavailable") from None


class CheckoutIn(BaseModel):
    """Only the product key. Anything else a client sends (price, amount, user id,
    provider product id) is ignored: those come from the catalog and the session."""

    product_key: str = Field(min_length=1, max_length=64)


class CheckoutOut(BaseModel):
    payment_id: uuid.UUID
    checkout_url: str


@router.post("/checkout", dependencies=[Depends(rate_limit("checkout", 10, 60)), Depends(require_csrf)])
async def checkout(
    body: CheckoutIn,
    idempotency_key: str | None = Header(default=None, max_length=128),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    config: BillingConfig = Depends(billing_config),
    provider: PaymentProvider = Depends(payment_provider),
) -> CheckoutOut:
    """Create a hosted checkout and return its URL for the browser to open.
    Send one Idempotency-Key per Buy click; a retry with it returns the same checkout."""
    try:
        started = await start_checkout(db, provider, config, user, product_key=body.product_key,
                                       idempotency_key=idempotency_key, return_base=get_settings().public_url)
    except CheckoutError as exc:
        raise HTTPException(status_code=ERROR_STATUS[exc.code], detail=exc.code) from None
    return CheckoutOut(payment_id=started.payment_id, checkout_url=started.checkout_url)


class WebhookAck(BaseModel):
    status: str


@router.post("/webhooks/dodo")
async def dodo_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    config: BillingConfig = Depends(billing_config),
    provider: PaymentProvider = Depends(payment_provider),
) -> WebhookAck:
    """Public: Dodo calls it. Authenticated by the signature over the exact raw body,
    not by cookies, so there is no CSRF check. 401 on a bad signature, 400 on a
    signed but malformed body, 5xx (so Dodo retries) when processing fails."""
    raw = await request.body()
    try:
        event = provider.handle_webhook(raw, request.headers)
    except InvalidSignature:
        raise HTTPException(status_code=401, detail="invalid_signature") from None
    except PaymentError:
        raise HTTPException(status_code=400, detail="malformed_event") from None
    try:
        result = await process_webhook(db, provider, config, event)
    except Exception:  # noqa: BLE001 - recorded in process_webhook; Dodo retries on 5xx
        raise HTTPException(status_code=500, detail="processing_failed") from None
    return WebhookAck(status=result)
