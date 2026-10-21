"""/api/billing: starting a checkout. Webhooks, status and the billing page come later."""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.billing.checkout import CheckoutError, start_checkout
from app.billing.config import BillingConfig, get_billing_config
from app.billing.providers import PaymentProvider, ProviderNotConfigured, get_payment_provider
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
