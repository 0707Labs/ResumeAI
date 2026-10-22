"""Read side of billing: public plans, payment status polling, the billing summary,
ledger history pages, and the customer-portal link."""

import uuid

import pytest
from sqlalchemy import text

from app.api.billing import billing_config, payment_provider
from app.billing.config import load_billing_config
from app.billing.providers import get_payment_provider
from tests.test_auth_signin import csrf
from tests.test_billing_checkout import FakeProvider, catalog
from tests.test_billing_webhooks import PACK, make_payment


class PortalProvider(FakeProvider):
    def __init__(self, url="https://portal/session"):
        super().__init__()
        self.url = url
        self.buyers = []

    async def get_portal_url(self, buyer, *, return_url=None):
        self.buyers.append((buyer, return_url))
        return self.url


@pytest.fixture
def ada(client, user_id):
    assert client.post(f"/test/login/{user_id}").status_code == 200
    return user_id


def sql(pg_engine, stmt, **params):
    with pg_engine.begin() as conn:
        conn.execute(text(stmt), params)


# --- plans -----------------------------------------------------------------------------------


def test_plans_are_public_and_come_from_the_catalog(client, api_app, monkeypatch):
    for name in ("DODO_API_KEY", "DODO_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    get_payment_provider.cache_clear()
    api_app.dependency_overrides[billing_config] = lambda: load_billing_config()
    try:
        body = client.get("/api/billing/plans").json()
    finally:
        get_payment_provider.cache_clear()
    keys = [p["key"] for p in body["plans"]]
    assert keys == ["credit_pack_5", "job_hunt_pass"]  # Pro hidden while its flag is off
    pack = body["plans"][0]
    assert (pack["credits"], pack["prices"]["INR"], pack["available"]) == (5, 49900, False)
    assert body["prices_include_tax"] is True and body["free_analyses_per_month"] == 2
    assert body["redownload_free_days"] == 7


def test_plans_show_pro_when_flagged_on_and_available_when_configured(client, api_app, monkeypatch):
    monkeypatch.setenv("DODO_API_KEY", "k")
    monkeypatch.setenv("DODO_WEBHOOK_SECRET", "whsec_" + "QUFBQUFBQUFBQUFBQUFBQQ==")
    monkeypatch.setenv("DODO_ENVIRONMENT", "test")
    get_payment_provider.cache_clear()
    api_app.dependency_overrides[billing_config] = lambda: catalog(pro=True)
    try:
        plans = client.get("/api/billing/plans").json()["plans"]
    finally:
        get_payment_provider.cache_clear()
    assert [(p["key"], p["available"]) for p in plans] == \
        [("credit_pack_5", True), ("job_hunt_pass", True), ("pro_monthly", True)]


# --- payment status --------------------------------------------------------------------------


def test_payment_status_is_only_for_its_owner(client, ada, pg_engine, new_browser):
    pid = make_payment(pg_engine, ada)
    body = client.get(f"/api/billing/payments/{pid}").json()
    assert (body["status"], body["product_key"], body["credits_balance"]) == ("created", "credit_pack_5", 0)
    assert client.get(f"/api/billing/payments/{uuid.uuid4()}").status_code == 404

    other = new_browser()
    with pg_engine.begin() as conn:
        bo = conn.execute(text(
            "INSERT INTO users (email, email_verified_at, activated_at, age_confirmed_at, terms_version,"
            " terms_accepted_at) VALUES ('bo@example.com', now(), now(), now(), 'v1', now()) RETURNING id"
        )).scalar_one()
    other.post(f"/test/login/{bo}")
    assert other.get(f"/api/billing/payments/{pid}").status_code == 404
    assert new_browser().get(f"/api/billing/payments/{pid}").status_code == 401


# --- summary and ledger ----------------------------------------------------------------------


def test_summary_shows_balance_pass_and_purchases(client, ada, pg_engine):
    pid = make_payment(pg_engine, ada)
    make_payment(pg_engine, ada, checkout_id="cks_abandoned")  # never paid: not listed
    sql(pg_engine, "UPDATE payments SET status = 'paid', amount_minor = 600, currency = 'USD', paid_at = now()"
                   " WHERE id = :i", i=pid)
    sql(pg_engine, "UPDATE users SET credits_balance = 5 WHERE id = :u", u=ada)
    sql(pg_engine, "INSERT INTO passes (user_id, product_key, reference_id, starts_at, expires_at, analyses_cap)"
                   " VALUES (:u, 'job_hunt_pass', 'pay_p', now(), now() + interval '29 days 2 hours', 40)", u=ada)
    sql(pg_engine, "INSERT INTO passes (user_id, product_key, reference_id, starts_at, expires_at, analyses_cap,"
                   " revoked_at) VALUES (:u, 'job_hunt_pass', 'pay_r', now(), now() + interval '30 days', 40, now())",
        u=ada)
    body = client.get("/api/billing/summary").json()
    assert body["credits_balance"] == 5
    assert [(p["days_remaining"], p["analyses_cap"]) for p in body["passes"]] == [(30, 40)]
    assert [(p["id"], p["name"], p["amount_minor"]) for p in body["purchases"]] == [(pid, "Credit pack", 600)]
    assert body["subscription"] is None and body["portal_available"] is False


def test_ledger_history_pages_newest_first(client, ada, pg_engine):
    for i in range(5):
        sql(pg_engine, "INSERT INTO credit_transactions (user_id, delta, reason, idempotency_key, balance_after)"
                       " VALUES (:u, 1, 'purchase', :k, :b)", u=ada, k=f"k{i}", b=i + 1)
    first = client.get("/api/billing/ledger?limit=3").json()
    assert [e["balance_after"] for e in first["entries"]] == [5, 4, 3]
    second = client.get(f"/api/billing/ledger?limit=3&before={first['next_before']}").json()
    assert [e["balance_after"] for e in second["entries"]] == [2, 1] and second["next_before"] is None


# --- portal ----------------------------------------------------------------------------------


def test_portal_link_uses_our_stored_customer(client, ada, api_app, pg_engine):
    provider = PortalProvider()
    api_app.dependency_overrides[payment_provider] = lambda: provider
    sql(pg_engine, "INSERT INTO billing_customers (user_id, provider, provider_customer_id)"
                   " VALUES (:u, 'dodo', 'cus_1')", u=ada)
    r = client.post("/api/billing/portal", headers=csrf(client))
    assert r.json() == {"url": "https://portal/session"}
    buyer, return_url = provider.buyers[0]
    assert buyer.provider_customer_id == "cus_1" and return_url.endswith("/account/billing")


def test_portal_needs_csrf_and_reports_unavailable(client, ada, api_app):
    api_app.dependency_overrides[payment_provider] = lambda: PortalProvider(url=None)
    assert client.post("/api/billing/portal").status_code == 403
    r = client.post("/api/billing/portal", headers=csrf(client))
    assert (r.status_code, r.json()["detail"]) == (404, "portal_unavailable")


def test_pack_snapshot_fixture_matches_catalog():
    assert PACK["credits"] == load_billing_config().products["credit_pack_5"].credits
