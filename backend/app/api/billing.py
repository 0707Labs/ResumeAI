"""/api/billing: the public catalog, checkout, the buyer's billing state, the
customer portal, and the provider's webhooks."""

import math
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.billing.checkout import CheckoutError, start_checkout
from app.billing.config import BillingConfig, get_billing_config
from app.billing.providers import PaymentProvider, ProviderNotConfigured, get_payment_provider
from app.billing.providers.base import Buyer, InvalidSignature, PaymentError
from app.billing.webhooks import process_webhook
from app.config import get_settings
from app.db.models import BillingCustomer, CreditTransaction, Pass, Payment, Subscription, User
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


async def live_billing(base: BillingConfig = Depends(billing_config), db: AsyncSession = Depends(get_db)) -> BillingConfig:
    """billing.toml plus runtime settings (Pro on/off, the free allowance, referral rules)."""
    from app.admin import settings as runtime

    return await runtime.live_config(db, base)


def payment_provider() -> PaymentProvider:
    try:
        return get_payment_provider()
    except ProviderNotConfigured:
        raise HTTPException(status_code=503, detail="payments_unavailable") from None


# --- catalog ----------------------------------------------------------------------------


class PlanOut(BaseModel):
    key: str
    kind: Literal["credit_pack", "pass", "subscription"]
    name: str
    prices: dict[str, int]  # minor units per currency
    credits: int | None
    pass_days: int | None
    fair_use_cap: int | None
    interval: str | None
    available: bool  # can be bought right now (provider configured, product set up)


class PlansOut(BaseModel):
    free_analyses_per_month: int  # free tailorings; downloads are always paid
    redownload_free_days: int  # re-downloading the same tailored resume is free this long
    prices_include_tax: bool
    plans: list[PlanOut]


@router.get("/plans")
async def plans(config: BillingConfig = Depends(live_billing)) -> PlansOut:
    """Public: what we sell, straight from billing.toml. Pro appears only when its flag is on."""
    try:
        mode = get_payment_provider().mode
    except ProviderNotConfigured:
        mode = None
    return PlansOut(
        free_analyses_per_month=config.free.analyses_per_month,
        redownload_free_days=config.downloads.redownload_free_days,
        prices_include_tax=config.display.prices_include_tax,
        plans=[
            PlanOut(key=p.key, kind=p.kind, name=p.name, prices=dict(p.prices), credits=p.credits,
                    pass_days=p.pass_days, fair_use_cap=p.fair_use_cap, interval=p.interval,
                    available=mode is not None and bool(p.dodo_product_id.for_mode(mode)))
            for p in config.products.values() if p.enabled
        ],
    )


# --- checkout ----------------------------------------------------------------------------


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
    config: BillingConfig = Depends(live_billing),
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


# --- the buyer's billing state ------------------------------------------------------------


class PaymentStatusOut(BaseModel):
    id: uuid.UUID
    product_key: str
    kind: str
    status: str
    credits_balance: int


@router.get("/payments/{payment_id}")
async def payment_status(payment_id: uuid.UUID, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)) -> PaymentStatusOut:
    """For the post-checkout page to poll. 'paid' means the webhook has granted the purchase."""
    payment = await db.scalar(select(Payment).where(Payment.id == payment_id, Payment.user_id == user.id))
    if payment is None:
        raise HTTPException(status_code=404, detail="not_found")
    return PaymentStatusOut(id=payment.id, product_key=payment.product_key, kind=payment.kind,
                            status=payment.status, credits_balance=user.credits_balance)


class PassOut(BaseModel):
    product_key: str
    starts_at: datetime
    expires_at: datetime
    days_remaining: int
    analyses_cap: int


class SubscriptionOut(BaseModel):
    product_key: str
    status: str
    current_period_end: datetime | None
    cancel_at_period_end: bool


class PurchaseOut(BaseModel):
    id: uuid.UUID
    product_key: str
    name: str
    status: str
    amount_minor: int | None
    currency: str | None
    created_at: datetime
    paid_at: datetime | None


class SummaryOut(BaseModel):
    credits_balance: int
    passes: list[PassOut]
    subscription: SubscriptionOut | None
    purchases: list[PurchaseOut]
    portal_available: bool


VISIBLE_PURCHASES = ("pending", "paid", "partially_refunded", "refunded", "disputed")


@router.get("/summary")
async def summary(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> SummaryOut:
    now = datetime.now(UTC)
    passes = await db.scalars(
        select(Pass).where(Pass.user_id == user.id, Pass.revoked_at.is_(None), Pass.expires_at > now)
        .order_by(Pass.starts_at)
    )
    sub = await db.scalar(
        select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.updated_at.desc())
    )
    purchases = await db.scalars(
        select(Payment).where(Payment.user_id == user.id, Payment.status.in_(VISIBLE_PURCHASES))
        .order_by(Payment.created_at.desc()).limit(20)
    )
    has_customer = await db.scalar(select(BillingCustomer.user_id).where(BillingCustomer.user_id == user.id))
    return SummaryOut(
        credits_balance=user.credits_balance,
        passes=[PassOut(product_key=p.product_key, starts_at=p.starts_at, expires_at=p.expires_at,
                        days_remaining=math.ceil((p.expires_at - max(now, p.starts_at)).total_seconds() / 86400),
                        analyses_cap=p.analyses_cap) for p in passes],
        subscription=SubscriptionOut(product_key=sub.product_key, status=sub.status,
                                     current_period_end=sub.current_period_end,
                                     cancel_at_period_end=sub.cancel_at_period_end) if sub else None,
        purchases=[PurchaseOut(id=p.id, product_key=p.product_key, name=p.snapshot.get("name", p.product_key),
                               status=p.status, amount_minor=p.amount_minor, currency=p.currency,
                               created_at=p.created_at, paid_at=p.paid_at) for p in purchases],
        portal_available=has_customer is not None or bool(get_settings().dodo_business_id),
    )


class LedgerEntryOut(BaseModel):
    id: int
    delta: int
    reason: str
    balance_after: int
    created_at: datetime


class LedgerOut(BaseModel):
    entries: list[LedgerEntryOut]
    next_before: int | None  # pass as ?before= for the next (older) page


@router.get("/ledger")
async def ledger_history(before: int | None = None, limit: int = 20, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)) -> LedgerOut:
    limit = max(1, min(limit, 100))
    query = select(CreditTransaction).where(CreditTransaction.user_id == user.id)
    if before is not None:
        query = query.where(CreditTransaction.id < before)
    rows = list(await db.scalars(query.order_by(CreditTransaction.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    return LedgerOut(
        entries=[LedgerEntryOut(id=r.id, delta=r.delta, reason=r.reason, balance_after=r.balance_after,
                                created_at=r.created_at) for r in page],
        next_before=page[-1].id if len(rows) > limit else None,
    )


class PortalOut(BaseModel):
    url: str


@router.post("/portal", dependencies=[Depends(rate_limit("portal", 10, 60)), Depends(require_csrf)])
async def portal(user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
                 provider: PaymentProvider = Depends(payment_provider)) -> PortalOut:
    """A link to Dodo's customer portal: receipts and invoices, and managing a subscription."""
    customer_id = await db.scalar(select(BillingCustomer.provider_customer_id).where(
        BillingCustomer.user_id == user.id, BillingCustomer.provider == provider.name))
    buyer = Buyer(user_id=user.id, email=user.email, name=user.name, provider_customer_id=customer_id)
    try:
        url = await provider.get_portal_url(buyer, return_url=f"{get_settings().public_url}/app/billing")
    except PaymentError:
        raise HTTPException(status_code=502, detail="portal_failed") from None
    if url is None:
        raise HTTPException(status_code=404, detail="portal_unavailable")
    return PortalOut(url=url)


# --- webhooks ----------------------------------------------------------------------------


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
