"""POST /api/billing/webhooks/dodo end to end: real signature verification (DodoProvider
with a mocked API client), real Postgres. Signature failures, replays, concurrency,
grants, refunds, disputes and subscriptions."""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.billing import billing_config, payment_provider
from app.billing import ledger
from app.billing.providers.base import WebhookEvent
from app.billing.webhooks import process_webhook
from tests.test_auth_signin import count, scalar
from tests.test_billing_checkout import catalog
from tests.test_dodo_provider import SECRET, FakeDodo, make, signed

URL = "/api/billing/webhooks/dodo"
PACK = {"catalog_version": 1, "provider_product_id": "pdt_pack", "credits": 5, "name": "Credit pack"}
PASS = {"catalog_version": 1, "provider_product_id": "pdt_pass", "pass_days": 30, "fair_use_cap": 40}


@pytest.fixture
def hook(api_app, client):
    """Deliver a signed event; returns the response."""
    provider = make(FakeDodo())
    api_app.dependency_overrides[payment_provider] = lambda: provider
    api_app.dependency_overrides[billing_config] = lambda: catalog(pro=True)

    def deliver(type_, data, *, msg_id=None, at=None, secret=SECRET, browser=None):
        body = json.dumps({"business_id": "bus_1", "type": type_, "data": data,
                           "timestamp": (at or datetime.now(UTC)).isoformat()}).encode()
        headers = signed(body, secret=secret, msg_id=msg_id or f"msg_{uuid.uuid4().hex}")
        return (browser or client).post(URL, content=body, headers={**headers, "Content-Type": "application/json"})

    return deliver


def make_payment(pg_engine, user_id, *, kind="credit_pack", product_key="credit_pack_5", snapshot=PACK,
                 checkout_id="cks_1") -> str:
    with pg_engine.begin() as conn:
        return str(conn.execute(text(
            "INSERT INTO payments (user_id, provider, mode, product_key, kind, snapshot, idempotency_key,"
            " provider_checkout_id) VALUES (:u, 'dodo', 'test', :p, :k, CAST(:s AS jsonb), :i, :c) RETURNING id"
        ), {"u": user_id, "p": product_key, "k": kind, "s": json.dumps(snapshot), "i": uuid.uuid4().hex,
            "c": checkout_id}).scalar_one())


def paid(user_id, *, checkout_id="cks_1", payment_id="pay_1", product_id="pdt_pack", amount=600, **extra):
    return {"payload_type": "Payment", "payment_id": payment_id, "checkout_session_id": checkout_id,
            "metadata": {"user_id": str(user_id), "product_key": "credit_pack_5"},
            "customer": {"customer_id": "cus_1", "email": "ada@example.com", "name": "Ada"},
            "total_amount": amount, "tax": 92, "currency": "USD", "settlement_amount": 560,
            "settlement_currency": "USD", "product_cart": [{"product_id": product_id, "quantity": 1}],
            "subscription_id": None, "status": "succeeded", **extra}


def refund(payment_id="pay_1", refund_id="rfd_1", partial=False, amount=None, currency="USD"):
    return {"payload_type": "Refund", "refund_id": refund_id, "payment_id": payment_id, "is_partial": partial,
            "amount": amount, "currency": currency, "status": "succeeded"}


def dispute(payment_id="pay_1", dispute_id="dsp_1", **extra):
    return {"payload_type": "Dispute", "dispute_id": dispute_id, "payment_id": payment_id, "amount": "6.00",
            "currency": "USD", "dispute_status": "dispute_opened", "dispute_stage": "dispute", **extra}


def balance(pg_engine, user_id) -> int:
    return scalar(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=user_id)


def status(pg_engine, payment_id) -> str:
    return scalar(pg_engine, "SELECT status FROM payments WHERE id = :i", i=payment_id)


def reviews(pg_engine, kind) -> int:
    return count(pg_engine, "billing_reviews", f"kind = '{kind}'")


# --- verification ----------------------------------------------------------------------


@pytest.mark.parametrize("tamper", ["signature", "secret", "missing", "stale"])
def test_bad_signatures_are_rejected_with_401_and_change_nothing(client, hook, user_id, pg_engine, tamper):
    make_payment(pg_engine, user_id)
    body = json.dumps({"business_id": "b", "type": "payment.succeeded", "data": paid(user_id),
                       "timestamp": datetime.now(UTC).isoformat()}).encode()
    headers = signed(body)
    if tamper == "signature":
        body = body.replace(b"pay_1", b"pay_9")
    elif tamper == "secret":
        headers = signed(body, secret="whsec_" + "QUFBQUFBQUFBQUFBQUFBQQ==")
    elif tamper == "missing":
        headers.pop("Webhook-Signature")
    else:
        headers = signed(body, ts=time.time() - 3600)
    r = client.post(URL, content=body, headers=headers)
    assert (r.status_code, r.json()["detail"]) == (401, "invalid_signature")
    assert count(pg_engine, "processed_webhook_events") == 0
    assert balance(pg_engine, user_id) == 0


def test_signed_but_malformed_body_is_400(client, hook, pg_engine):
    body = b'{"type": "payment.succeeded"}'
    assert client.post(URL, content=body, headers=signed(body)).status_code == 400


def test_unknown_event_type_is_acknowledged_and_ignored(hook, pg_engine):
    r = hook("something.brand_new", {"x": 1}, msg_id="msg_new")
    assert (r.status_code, r.json()["status"]) == (200, "ignored")
    assert scalar(pg_engine, "SELECT outcome FROM processed_webhook_events WHERE event_id = 'msg_new'") == "ignored"


def test_webhook_needs_no_session_or_csrf(new_browser, api_app, hook, user_id, pg_engine):
    make_payment(pg_engine, user_id)
    stranger = new_browser()  # no cookies, no CSRF header
    assert hook("payment.succeeded", paid(user_id), browser=stranger).status_code == 200


# --- grants and idempotency ----------------------------------------------------------------


def test_valid_payment_grants_credits_once(hook, user_id, pg_engine):
    pid = make_payment(pg_engine, user_id)
    r = hook("payment.succeeded", paid(user_id), msg_id="msg_1")
    assert (r.status_code, r.json()["status"]) == (200, "processed")
    assert balance(pg_engine, user_id) == 5
    row = scalar(pg_engine, "SELECT row_to_json(p) FROM payments p WHERE id = :i", i=pid)
    assert (row["status"], row["provider_payment_id"], row["amount_minor"], row["tax_minor"], row["currency"]) \
        == ("paid", "pay_1", 600, 92, "USD")
    assert scalar(pg_engine, "SELECT reference_id FROM credit_transactions") == "pay_1"
    assert scalar(pg_engine, "SELECT provider_customer_id FROM billing_customers") == "cus_1"


def test_replayed_event_is_ignored(hook, user_id, pg_engine):
    make_payment(pg_engine, user_id)
    results = [hook("payment.succeeded", paid(user_id), msg_id="msg_1").json()["status"] for _ in range(3)]
    assert results == ["processed", "duplicate", "duplicate"]
    assert balance(pg_engine, user_id) == 5
    assert count(pg_engine, "credit_transactions") == 1


def test_same_payment_under_a_new_delivery_id_grants_once(hook, user_id, pg_engine):
    make_payment(pg_engine, user_id)
    hook("payment.succeeded", paid(user_id))
    assert hook("payment.succeeded", paid(user_id)).json()["status"] == "ignored"
    assert balance(pg_engine, user_id) == 5


def test_concurrent_deliveries_grant_once(pg_url, api_app, user_id, pg_engine):
    """Six simultaneous first deliveries of one event, each on its own connection."""
    make_payment(pg_engine, user_id)
    provider = make(FakeDodo())
    event = WebhookEvent(event_id="msg_1", type="payment.succeeded", occurred_at=datetime.now(UTC),
                         data=paid(user_id))

    async def race():
        engine = create_async_engine(pg_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def deliver():
            async with sessions() as db:
                return await process_webhook(db, provider, catalog(), event)
        try:
            return await asyncio.gather(*(deliver() for _ in range(6)))
        finally:
            await engine.dispose()

    results = asyncio.run(race())
    assert sorted(results) == ["duplicate"] * 5 + ["processed"]
    assert balance(pg_engine, user_id) == 5
    assert count(pg_engine, "credit_transactions") == 1


def test_failure_rolls_back_records_and_succeeds_on_retry(hook, user_id, pg_engine, monkeypatch):
    make_payment(pg_engine, user_id)
    real = ledger.grant

    async def broken(*a, **kw):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(ledger, "grant", broken)
    assert hook("payment.succeeded", paid(user_id), msg_id="msg_1").status_code == 500
    row = scalar(pg_engine, "SELECT row_to_json(e) FROM processed_webhook_events e")
    assert (row["processed_at"], row["failures"], row["last_error"]) == (None, 1, "RuntimeError")
    assert status(pg_engine, scalar(pg_engine, "SELECT id FROM payments")) == "created"

    monkeypatch.setattr(ledger, "grant", real)
    assert hook("payment.succeeded", paid(user_id), msg_id="msg_1").json()["status"] == "processed"
    assert balance(pg_engine, user_id) == 5


def test_pass_purchase_grants_a_30_day_pass(hook, user_id, pg_engine):
    make_payment(pg_engine, user_id, kind="pass", product_key="job_hunt_pass", snapshot=PASS)
    hook("payment.succeeded", paid(user_id, product_id="pdt_pass") | {"metadata": {"user_id": str(user_id)}})
    row = scalar(pg_engine, "SELECT row_to_json(p) FROM passes p")
    starts, ends = (datetime.fromisoformat(row[k]) for k in ("starts_at", "expires_at"))
    assert (ends - starts, row["analyses_cap"], row["reference_id"]) == (timedelta(days=30), 40, "pay_1")
    assert balance(pg_engine, user_id) == 0


@pytest.mark.parametrize("change", [
    {"product_cart": [{"product_id": "pdt_other", "quantity": 1}]},
    {"product_cart": [{"product_id": "pdt_pack", "quantity": 3}]},
    {"metadata": {"user_id": str(uuid.uuid4()), "product_key": "credit_pack_5"}},
    {"metadata": {"product_key": "job_hunt_pass"}},
])
def test_payment_that_does_not_match_the_checkout_is_flagged_not_granted(hook, user_id, pg_engine, change):
    make_payment(pg_engine, user_id)
    assert hook("payment.succeeded", paid(user_id) | change).json()["status"] == "flagged"
    assert balance(pg_engine, user_id) == 0
    assert reviews(pg_engine, "payment_mismatch") == 1


def test_payment_for_an_unknown_checkout_is_flagged(hook, user_id, pg_engine):
    assert hook("payment.succeeded", paid(user_id, checkout_id="cks_unknown")).json()["status"] == "flagged"
    assert reviews(pg_engine, "unknown_payment") == 1


def test_renewal_payment_is_not_a_new_purchase(hook, user_id, pg_engine):
    r = hook("payment.succeeded", paid(user_id, checkout_id=None, subscription_id="sub_1"))
    assert r.json()["status"] == "ignored"
    assert count(pg_engine, "billing_reviews") == 0


def test_failed_then_succeeded_grants_once_and_late_failure_cannot_unpay(hook, user_id, pg_engine):
    pid = make_payment(pg_engine, user_id)
    hook("payment.processing", {"checkout_session_id": "cks_1"})
    assert status(pg_engine, pid) == "pending"
    hook("payment.failed", {"checkout_session_id": "cks_1"})
    assert status(pg_engine, pid) == "failed"
    hook("payment.succeeded", paid(user_id))
    hook("payment.failed", {"checkout_session_id": "cks_1"})
    assert (status(pg_engine, pid), balance(pg_engine, user_id)) == ("paid", 5)


# --- refunds -------------------------------------------------------------------------------


def buy_pack(hook, pg_engine, user_id) -> str:
    pid = make_payment(pg_engine, user_id)
    hook("payment.succeeded", paid(user_id))
    return pid


def spend(pg_engine, user_id, n):
    with pg_engine.begin() as conn:
        for _ in range(n):
            conn.execute(text(
                "WITH u AS (UPDATE users SET credits_balance = credits_balance - 1 WHERE id = :u"
                " RETURNING credits_balance) INSERT INTO credit_transactions (user_id, delta, reason,"
                " idempotency_key, balance_after) SELECT :u, -1, 'analysis_charge', :k, credits_balance FROM u"
            ), {"u": user_id, "k": uuid.uuid4().hex})


def test_full_refund_takes_back_credits_exactly_once(hook, user_id, pg_engine):
    pid = buy_pack(hook, pg_engine, user_id)
    for _ in range(2):  # same refund, two deliveries with different ids
        assert hook("refund.succeeded", refund()).status_code == 200
    assert (balance(pg_engine, user_id), status(pg_engine, pid)) == (0, "refunded")
    assert count(pg_engine, "credit_transactions", "reason = 'purchase_reversal'") == 1


def test_refund_after_credits_were_spent_never_goes_negative_and_flags(hook, user_id, pg_engine):
    buy_pack(hook, pg_engine, user_id)
    spend(pg_engine, user_id, 3)
    hook("refund.succeeded", refund())
    assert balance(pg_engine, user_id) == 0
    detail = scalar(pg_engine, "SELECT detail FROM billing_reviews WHERE kind = 'credits_already_used'")
    assert (detail["requested"], detail["shortfall"]) == (5, 3)


def test_partial_refund_takes_back_a_proportional_share(hook, user_id, pg_engine):
    pid = buy_pack(hook, pg_engine, user_id)
    hook("refund.succeeded", refund(partial=True, amount=240))  # 240/600 of 5 credits = 2
    assert (balance(pg_engine, user_id), status(pg_engine, pid)) == (3, "partially_refunded")
    hook("refund.succeeded", refund(refund_id="rfd_2"))  # then the rest, in full
    assert (balance(pg_engine, user_id), status(pg_engine, pid)) == (0, "refunded")


def test_partial_refund_in_another_currency_is_flagged(hook, user_id, pg_engine):
    buy_pack(hook, pg_engine, user_id)
    assert hook("refund.succeeded", refund(partial=True, amount=200, currency="INR")).json()["status"] == "flagged"
    assert (balance(pg_engine, user_id), reviews(pg_engine, "partial_refund")) == (5, 1)


def test_pass_refund_revokes_the_pass(hook, user_id, pg_engine):
    make_payment(pg_engine, user_id, kind="pass", product_key="job_hunt_pass", snapshot=PASS)
    hook("payment.succeeded", paid(user_id, product_id="pdt_pass") | {"metadata": {"user_id": str(user_id)}})
    hook("refund.succeeded", refund())
    assert scalar(pg_engine, "SELECT revoked_at IS NOT NULL FROM passes") is True


def test_refund_failed_changes_nothing(hook, user_id, pg_engine):
    buy_pack(hook, pg_engine, user_id)
    assert hook("refund.failed", refund() | {"status": "failed"}).json()["status"] == "ignored"
    assert balance(pg_engine, user_id) == 5


# --- disputes ------------------------------------------------------------------------------


def test_dispute_opened_then_lost(hook, user_id, pg_engine):
    pid = buy_pack(hook, pg_engine, user_id)
    hook("dispute.opened", dispute())
    assert (status(pg_engine, pid), reviews(pg_engine, "dispute_opened"), balance(pg_engine, user_id)) == \
        ("disputed", 1, 5)
    hook("dispute.lost", dispute(is_resolved_by_rdr=True))
    assert (status(pg_engine, pid), balance(pg_engine, user_id)) == ("refunded", 0)


def test_refund_then_lost_dispute_does_not_take_credits_twice(hook, user_id, pg_engine):
    buy_pack(hook, pg_engine, user_id)
    hook("refund.succeeded", refund())
    # A later purchase whose credits must not be eaten by the old payment's dispute.
    buy_pack_again = make_payment(pg_engine, user_id, checkout_id="cks_2")
    hook("payment.succeeded", paid(user_id, checkout_id="cks_2", payment_id="pay_2"))
    hook("dispute.lost", dispute())
    assert status(pg_engine, buy_pack_again) == "paid"
    assert balance(pg_engine, user_id) == 5


def test_dispute_won_restores_paid(hook, user_id, pg_engine):
    pid = buy_pack(hook, pg_engine, user_id)
    hook("dispute.opened", dispute())
    hook("dispute.won", dispute())
    assert (status(pg_engine, pid), balance(pg_engine, user_id)) == ("paid", 5)


# --- subscriptions -------------------------------------------------------------------------


def sub(user_id, status_="active", next_billing="2026-12-01T00:00:00Z", **extra):
    return {"payload_type": "Subscription", "subscription_id": "sub_1", "product_id": "pdt_pro",
            "status": status_, "next_billing_date": next_billing, "cancel_at_next_billing_date": False,
            "metadata": {"user_id": str(user_id)}, "customer": {"customer_id": "cus_1"}, **extra}


def sub_row(pg_engine):
    return scalar(pg_engine, "SELECT row_to_json(s) FROM subscriptions s")


def test_subscription_lifecycle(hook, user_id, pg_engine):
    t0 = datetime.now(UTC)
    hook("subscription.active", sub(user_id), at=t0)
    row = sub_row(pg_engine)
    assert (row["status"], row["product_key"], row["user_id"]) == ("active", "pro_monthly", str(user_id))
    hook("subscription.renewed", sub(user_id, next_billing="2027-01-01T00:00:00Z"), at=t0 + timedelta(days=30))
    assert sub_row(pg_engine)["current_period_end"].startswith("2027-01-01")
    hook("subscription.cancelled", sub(user_id, "cancelled"), at=t0 + timedelta(days=31))
    assert sub_row(pg_engine)["status"] == "cancelled"


def test_out_of_order_subscription_event_does_not_overwrite_newer_state(hook, user_id, pg_engine):
    t0 = datetime.now(UTC)
    hook("subscription.cancelled", sub(user_id, "cancelled"), at=t0)
    assert hook("subscription.active", sub(user_id), at=t0 - timedelta(minutes=5)).json()["status"] == "ignored"
    assert sub_row(pg_engine)["status"] == "cancelled"


def test_subscription_for_an_unknown_buyer_is_retried_until_known(hook, user_id, pg_engine):
    data = sub(user_id) | {"metadata": {}}
    assert hook("subscription.active", data, msg_id="msg_sub").status_code == 500
    with pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO billing_customers (user_id, provider, provider_customer_id)"
                          " VALUES (:u, 'dodo', 'cus_1')"), {"u": user_id})
    assert hook("subscription.active", data, msg_id="msg_sub").json()["status"] == "processed"
    assert scalar(pg_engine, "SELECT failures FROM processed_webhook_events WHERE event_id = 'msg_sub'") == 1


def test_subscription_for_a_product_we_do_not_sell_is_ignored(hook, user_id, pg_engine):
    assert hook("subscription.active", sub(user_id) | {"product_id": "pdt_x"}).json()["status"] == "ignored"
    assert count(pg_engine, "subscriptions") == 0


def test_unconfigured_payments_answer_503(client, api_app, monkeypatch):
    from app.billing.providers import get_payment_provider
    api_app.dependency_overrides.pop(payment_provider, None)
    for name in ("DODO_API_KEY", "DODO_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    get_payment_provider.cache_clear()
    try:
        assert client.post(URL, content=b"{}").status_code == 503
    finally:
        get_payment_provider.cache_clear()
