"""The local test-mode helpers in scripts/: the signed webhook sender produces events our
endpoint accepts and processes, and the product checker catches catalog drift."""

import importlib.util
import json
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from dodopayments import NotFoundError
from standardwebhooks import Webhook

from app.api.billing import billing_config, payment_provider
from app.billing.config import load_billing_config
from tests.test_auth_signin import scalar
from tests.test_billing_checkout import IDS, catalog
from tests.test_billing_webhooks import PACK, make_payment
from tests.test_dodo_provider import SECRET, FakeDodo, make

SCRIPTS = Path(__file__).parent.parent / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sender = load("dodo_send_webhook")
checker = load("dodo_check_products")


def args(**kw):
    return Namespace(**{"amount": None, "currency": "USD", "partial": None, "refund_id": None,
                        "dispute_id": None, **kw})


def send(client, event_type, row, a):
    body = json.dumps({"business_id": "b", "type": event_type, "timestamp": datetime.now(UTC).isoformat(),
                       "data": sender.build(event_type, row, a)})
    now = datetime.now(UTC)
    headers = {"webhook-id": f"msg_{event_type}", "webhook-timestamp": str(int(now.timestamp())),
               "webhook-signature": Webhook(SECRET).sign(f"msg_{event_type}", now, body)}
    return client.post("/api/billing/webhooks/dodo", content=body, headers=headers)


def test_sender_payloads_grant_then_refund(client, api_app, user_id, pg_engine):
    api_app.dependency_overrides[payment_provider] = lambda: make(FakeDodo())
    api_app.dependency_overrides[billing_config] = lambda: catalog()
    pid = make_payment(pg_engine, user_id)
    row = scalar(pg_engine, "SELECT row_to_json(p) FROM payments p WHERE id = :i", i=pid)
    assert send(client, "payment.succeeded", row, args()).json()["status"] == "processed"
    assert scalar(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=user_id) == 5
    row = scalar(pg_engine, "SELECT row_to_json(p) FROM payments p WHERE id = :i", i=pid)
    assert send(client, "refund.succeeded", row, args(refund_id="rfd_1")).json()["status"] == "processed"
    assert scalar(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=user_id) == 0


def test_sender_refuses_outside_test_mode(monkeypatch):
    monkeypatch.setenv("DODO_ENVIRONMENT", "live")
    monkeypatch.setattr("sys.argv", ["x", "payment.succeeded", "--payment-row", "x"])
    with pytest.raises(SystemExit, match="not 'test'"):
        sender.main()


class FakeProducts:
    def __init__(self, products, localized):
        self.products, self.localized = products, localized
        self.localized_prices = SimpleNamespace(list=lambda pid: SimpleNamespace(items=self.localized.get(pid, [])))

    def retrieve(self, pid):
        if pid not in self.products:
            raise NotFoundError("missing", response=SimpleNamespace(status_code=404, headers={}, request=None),
                                body=None)
        return self.products[pid]


def remote(recurring=False, currency="USD", price=600, tax_inclusive=True):
    return SimpleNamespace(is_recurring=recurring,
                           price=SimpleNamespace(currency=currency, price=price, tax_inclusive=tax_inclusive))


def inr(amount):
    return SimpleNamespace(currency="INR", amount=amount, country_code=None)


def test_checker_passes_when_dodo_matches_the_catalog():
    products = FakeProducts({"pdt_pack": remote(), "pdt_pass": remote(price=1200)},
                            {"pdt_pack": [inr(49900)], "pdt_pass": [inr(99900)]})
    assert checker.check(SimpleNamespace(products=products), catalog(), "test") == []


def test_checker_reports_drift():
    products = FakeProducts({"pdt_pack": remote(price=700, tax_inclusive=False)}, {"pdt_pack": [inr(49900)]})
    problems = checker.check(SimpleNamespace(products=products), catalog(), "test")
    assert any("USD is 700 in Dodo, 600" in p for p in problems)
    assert any("not tax-inclusive" in p for p in problems)
    assert any("pdt_pass not found" in p for p in problems)
    assert checker.check(SimpleNamespace(products=products), load_billing_config(), "test")[0] == \
        "credit_pack_5: no test product id in billing.toml"


def test_fixture_ids_cover_the_catalog():
    assert set(IDS) == set(load_billing_config().products) and PACK["credits"] == 5
