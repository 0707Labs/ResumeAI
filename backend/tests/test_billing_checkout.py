"""POST /api/billing/checkout: authenticated, CSRF-protected, catalog-driven; client
prices and user ids are ignored; idempotent per key; nothing is granted here."""

import uuid

import pytest
from sqlalchemy import text

from app.api.billing import billing_config, payment_provider
from app.billing.config import load_billing_config
from app.billing.providers import get_payment_provider
from app.billing.providers.base import Buyer, CheckoutSession, PaymentError
from tests.test_auth_signin import count, csrf, scalar

IDS = {"credit_pack_5": "pdt_pack", "job_hunt_pass": "pdt_pass", "pro_monthly": "pdt_pro"}


class FakeProvider:
    name = "dodo"
    mode = "test"

    def __init__(self):
        self.calls: list[tuple[Buyer, object, dict]] = []
        self.fail = False

    async def create_checkout(self, buyer, product, *, return_url, cancel_url=None):
        self.calls.append((buyer, product, {"return_url": return_url, "cancel_url": cancel_url}))
        if self.fail:
            raise PaymentError("boom")
        n = len(self.calls)
        return CheckoutSession(provider_checkout_id=f"cks_{n}", url=f"https://test.checkout/cks_{n}")


def catalog(pro: bool = False):
    config = load_billing_config(pro_enabled=pro)
    products = {
        k: p.model_copy(update={"dodo_product_id": p.dodo_product_id.model_copy(update={"test": IDS[k]})})
        for k, p in config.products.items()
    }
    return config.model_copy(update={"products": products})


@pytest.fixture
def fake(api_app):
    provider = FakeProvider()
    api_app.dependency_overrides[payment_provider] = lambda: provider
    api_app.dependency_overrides[billing_config] = lambda: catalog()
    return provider


@pytest.fixture
def ada(client, user_id):
    assert client.post(f"/test/login/{user_id}").status_code == 200
    return user_id


def buy(client, body, key=None):
    headers = csrf(client)
    if key:
        headers["Idempotency-Key"] = key
    return client.post("/api/billing/checkout", json=body, headers=headers)


def test_checkout_needs_a_session(client, fake):
    assert buy(client, {"product_key": "credit_pack_5"}).status_code == 401
    assert fake.calls == []


def test_checkout_needs_csrf(client, ada, fake):
    r = client.post("/api/billing/checkout", json={"product_key": "credit_pack_5"})
    assert r.status_code == 403
    assert fake.calls == []


def test_checkout_returns_url_and_records_the_attempt(client, ada, fake, pg_engine):
    r = buy(client, {"product_key": "credit_pack_5"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["checkout_url"] == "https://test.checkout/cks_1"
    row = scalar(pg_engine, "SELECT row_to_json(p) FROM payments p WHERE id = :i", i=out["payment_id"])
    assert (row["user_id"], row["product_key"], row["kind"], row["status"]) == \
        (str(ada), "credit_pack_5", "credit_pack", "created")
    assert (row["provider"], row["mode"], row["provider_checkout_id"]) == ("dodo", "test", "cks_1")
    assert row["snapshot"]["credits"] == 5 and row["snapshot"]["catalog_version"] == 1
    _, _, urls = fake.calls[0]
    assert urls == {"return_url": f"http://localhost:3000/billing/success?payment={out['payment_id']}",
                    "cancel_url": "http://localhost:3000/pricing"}
    # Checkout never grants anything; only a verified webhook does.
    assert count(pg_engine, "credit_transactions") == 0
    assert scalar(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=ada) == 0


def test_tampered_price_and_user_id_are_ignored(client, ada, fake, pg_engine):
    victim = uuid.uuid4()
    r = buy(client, {"product_key": "credit_pack_5", "price": 1, "amount": 1, "prices": {"INR": 1},
                     "credits": 999, "user_id": str(victim), "product_id": "pdt_evil", "currency": "INR"})
    assert r.status_code == 200, r.text
    buyer, product, _ = fake.calls[0]
    assert buyer.user_id == ada and buyer.email == "ada@example.com"
    assert product.credits == 5 and product.prices == catalog().products["credit_pack_5"].prices
    assert product.dodo_product_id.test == "pdt_pack"
    row = scalar(pg_engine, "SELECT row_to_json(p) FROM payments p WHERE id = :i", i=r.json()["payment_id"])
    assert row["user_id"] == str(ada) and row["snapshot"]["credits"] == 5


@pytest.mark.parametrize("key", ["credit_pack_500", "", "pro_monthly"])
def test_unknown_empty_or_flagged_off_products_are_refused(client, ada, fake, key):
    assert buy(client, {"product_key": key}).status_code in (404, 422)
    assert fake.calls == []


def test_pro_is_sold_when_the_flag_is_on(client, ada, fake, api_app):
    api_app.dependency_overrides[billing_config] = lambda: catalog(pro=True)
    assert buy(client, {"product_key": "pro_monthly"}).status_code == 200
    assert fake.calls[0][1].kind == "subscription"


def test_product_without_an_id_in_this_mode_is_refused(client, ada, fake, api_app):
    api_app.dependency_overrides[billing_config] = lambda: load_billing_config()  # shipped: no ids yet
    assert buy(client, {"product_key": "credit_pack_5"}).json()["detail"] == "product_unavailable"
    assert fake.calls == []


def test_same_idempotency_key_returns_the_same_checkout(client, ada, fake, pg_engine):
    first = buy(client, {"product_key": "job_hunt_pass"}, key="click-1").json()
    again = buy(client, {"product_key": "job_hunt_pass"}, key="click-1").json()
    assert first == again and len(fake.calls) == 1
    assert count(pg_engine, "payments") == 1
    assert buy(client, {"product_key": "job_hunt_pass"}, key="click-2").json() != first


def test_idempotency_key_reused_for_another_product_is_refused(client, ada, fake):
    buy(client, {"product_key": "job_hunt_pass"}, key="click-1")
    r = buy(client, {"product_key": "credit_pack_5"}, key="click-1")
    assert (r.status_code, r.json()["detail"]) == (422, "idempotency_key_reused")


def test_provider_failure_is_502_and_marks_the_attempt(client, ada, fake, pg_engine):
    fake.fail = True
    r = buy(client, {"product_key": "credit_pack_5"})
    assert (r.status_code, r.json()["detail"]) == (502, "checkout_failed")
    assert scalar(pg_engine, "SELECT status FROM payments") == "checkout_failed"


def test_known_dodo_customer_is_reused(client, ada, fake, pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO billing_customers (user_id, provider, provider_customer_id)"
                          " VALUES (:u, 'dodo', 'cus_1')"), {"u": ada})
    buy(client, {"product_key": "credit_pack_5"})
    assert fake.calls[0][0].provider_customer_id == "cus_1"


def test_unconfigured_payments_answer_503(client, ada, api_app, monkeypatch):
    api_app.dependency_overrides[billing_config] = lambda: catalog()
    for name in ("DODO_API_KEY", "DODO_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    get_payment_provider.cache_clear()
    try:
        r = buy(client, {"product_key": "credit_pack_5"})
    finally:
        get_payment_provider.cache_clear()
    assert (r.status_code, r.json()["detail"]) == (503, "payments_unavailable")
