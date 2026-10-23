"""The paywall end to end, in test mode: a download without credits is refused (402, no
file); the user buys a credit pack (checkout through the Dodo provider with a mocked
API); Dodo's signed payment.succeeded webhook grants the credits; the same download now
succeeds and spends exactly one credit. Real signature checks, real Postgres."""

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.api.billing import billing_config, payment_provider
from tests.test_analyses import fixture_text
from tests.test_auth_signin import csrf, scalar
from tests.test_billing_checkout import IDS, catalog
from tests.test_dodo_provider import FakeDodo, make, signed


@pytest.fixture
def shopper(api_app, new_browser, user_id):
    provider = make(FakeDodo())
    api_app.dependency_overrides[payment_provider] = lambda: provider
    api_app.dependency_overrides[billing_config] = lambda: catalog()
    browser = new_browser()
    assert browser.post(f"/test/login/{user_id}").status_code == 200
    browser.headers.update(csrf(browser))
    return browser


def webhook(browser, data, msg_id):
    body = json.dumps({"business_id": "bus_1", "type": "payment.succeeded", "data": data,
                       "timestamp": datetime.now(UTC).isoformat()}).encode()
    return browser.post("/api/billing/webhooks/dodo", content=body,
                        headers={**signed(body, msg_id=msg_id), "Content-Type": "application/json"})


def test_purchase_then_webhook_then_download(shopper, user_id, pg_engine):
    resume = shopper.post("/api/resume/parse", files={"file": ("r.txt", fixture_text("resume_analyst.txt"))}).json()
    jd = shopper.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")}).json()
    aid = shopper.post("/api/analyses", json={"resume": resume, "jd": jd}).json()["analysis_id"]
    tailored = shopper.post("/api/tailor", json={"resume": resume, "jd": jd, "use_llm": False},
                            headers={"X-Analysis-Id": aid}).json()
    ask = lambda: shopper.post("/api/downloads/docx", headers={"X-Analysis-Id": aid},  # noqa: E731
                               json={"resume": resume, "tailored": tailored, "jd_text": jd["raw_text"]})

    # 1. No credits: 402 and nothing rendered or recorded.
    refused = ask()
    assert (refused.status_code, refused.json()["detail"]) == (402, "no_credits")
    assert scalar(pg_engine, "SELECT count(*) FROM downloads") == 0

    # 2. Checkout (test mode). The redirect back proves nothing; the payment is pending.
    started = shopper.post("/api/billing/checkout", json={"product_key": "credit_pack_5"},
                           headers={"Idempotency-Key": str(uuid.uuid4())})
    assert started.status_code == 200, started.text
    payment_id = started.json()["payment_id"]
    assert shopper.get(f"/api/billing/payments/{payment_id}").json()["status"] in {"created", "pending"}
    assert ask().status_code == 402

    # 3. Dodo's signed webhook grants the pack (once, even if redelivered).
    checkout_id = scalar(pg_engine, "SELECT provider_checkout_id FROM payments WHERE id = :p", p=payment_id)
    data = {"payload_type": "Payment", "payment_id": "pay_e2e", "checkout_session_id": checkout_id,
            "metadata": {"user_id": str(user_id), "product_key": "credit_pack_5"},
            "customer": {"customer_id": "cus_1", "email": "ada@example.com", "name": "Ada"},
            "total_amount": 600, "tax": 92, "currency": "USD", "settlement_amount": 560,
            "settlement_currency": "USD", "product_cart": [{"product_id": IDS["credit_pack_5"], "quantity": 1}],
            "subscription_id": None, "status": "succeeded"}
    assert webhook(shopper, data, "msg_paid").status_code == 200
    assert webhook(shopper, data, "msg_paid").status_code == 200  # replay
    status = shopper.get(f"/api/billing/payments/{payment_id}").json()
    assert (status["status"], status["credits_balance"]) == ("paid", 5)

    # 4. The download now succeeds and spends exactly one credit.
    link = ask()
    assert link.status_code == 200 and link.json()["paid_with"] == "credit"
    file = shopper.get(link.json()["url"])
    assert file.status_code == 200 and file.content[:2] == b"PK"
    assert scalar(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=user_id) == 4
    # /admin/quality counts: what the tailoring produced, and what the download carried (counts only).
    generated, approved = (scalar(pg_engine, f"SELECT {c} FROM analyses WHERE id = :a", a=aid)
                           for c in ("bullets_generated", "bullets_approved"))
    assert generated == len(tailored["bullets"]) and approved == sum(b["review"] == "approved" for b in tailored["bullets"])
    again = ask()  # the same resume again: inside the re-download window
    assert again.json()["paid_with"] == "window" and again.json()["credits_balance"] == 4
