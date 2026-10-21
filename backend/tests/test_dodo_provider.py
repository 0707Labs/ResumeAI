"""DodoProvider against a mocked Dodo API (no network): checkout request shape,
webhook signature verification, portal links and refunds."""

import asyncio
import base64
import json
import time
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from dodopayments import AsyncDodoPayments
from standardwebhooks import Webhook

from app.billing.config import load_billing_config
from app.billing.providers.base import (
    Buyer,
    InvalidSignature,
    PaymentError,
    ProductUnavailable,
    ProviderNotConfigured,
)
from app.billing.providers.dodo import DodoProvider

SECRET = "whsec_" + base64.b64encode(b"test-webhook-secret-32-bytes!!!!").decode()
BUYER = Buyer(user_id=uuid.UUID(int=7), email="ada@example.com", name="Ada")


class FakeDodo:
    """Records requests and answers like the Dodo API."""

    def __init__(self, status: int = 200):
        self.requests: list[httpx.Request] = []
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "nope"})
        path = request.url.path
        if path == "/checkouts":
            return httpx.Response(200, json={"session_id": "cks_1", "checkout_url": "https://test.checkout/cks_1"})
        if path.endswith("/customer-portal/session"):
            return httpx.Response(200, json={"link": "https://portal/session"})
        if path == "/refunds":
            return httpx.Response(200, json=refund_json())
        return httpx.Response(404, json={})

    def body(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].content)


def refund_json(status: str = "pending") -> dict:
    return {"refund_id": "rfd_1", "payment_id": "pay_1", "business_id": "bus_1", "brand_id": "br_1",
            "status": status, "is_partial": False, "created_at": "2026-10-21T00:00:00Z", "metadata": {},
            "customer": {"customer_id": "cus_1", "email": "ada@example.com", "name": "Ada"}}


def make(fake: FakeDodo, *, environment: str = "test", business_id: str = "") -> DodoProvider:
    client = AsyncDodoPayments(
        bearer_token="test-key", webhook_key=SECRET, environment="test_mode", base_url=None,
        max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(fake)),
    )
    return DodoProvider(api_key="test-key", webhook_secret=SECRET, environment=environment,
                        business_id=business_id, client=client)


def catalog(**ids):
    config = load_billing_config(pro_enabled=True)
    products = {}
    for key, product in config.products.items():
        products[key] = product.model_copy(update={
            "dodo_product_id": product.dodo_product_id.model_copy(update={"test": ids.get(key, "")})
        })
    return products


def run(coro):
    return asyncio.run(coro)


# --- configuration -------------------------------------------------------------------


@pytest.mark.parametrize("kw", [
    {"api_key": "", "webhook_secret": SECRET, "environment": "test"},
    {"api_key": "k", "webhook_secret": "", "environment": "test"},
    {"api_key": "k", "webhook_secret": SECRET, "environment": "production"},
    {"api_key": "k", "webhook_secret": SECRET, "environment": ""},
])
def test_missing_or_unknown_settings_refuse_to_build(kw):
    with pytest.raises(ProviderNotConfigured):
        DodoProvider(**kw)


def test_environment_maps_to_the_sdk_host_ignoring_sdk_env_vars(monkeypatch):
    monkeypatch.setenv("DODO_PAYMENTS_BASE_URL", "https://live.dodopayments.com")
    provider = DodoProvider(api_key="k", webhook_secret=SECRET, environment="test")
    assert str(provider._client.base_url).startswith("https://test.dodopayments.com")


# --- checkout ------------------------------------------------------------------------


def test_checkout_sends_config_product_and_our_metadata():
    fake = FakeDodo()
    product = catalog(credit_pack_5="pdt_pack")["credit_pack_5"]
    session = run(make(fake).create_checkout(BUYER, product, return_url="https://app/return",
                                             cancel_url="https://app/pricing"))
    assert (session.provider_checkout_id, session.url) == ("cks_1", "https://test.checkout/cks_1")
    body = fake.body()
    assert body["product_cart"] == [{"product_id": "pdt_pack", "quantity": 1}]
    assert body["metadata"] == {"user_id": str(BUYER.user_id), "product_key": "credit_pack_5"}
    assert body["customer"] == {"email": "ada@example.com", "name": "Ada"}
    assert body["feature_flags"] == {"allow_discount_code": False}
    assert "amount" not in json.dumps(body)  # never a price: Dodo charges what the product says


def test_checkout_reuses_a_known_dodo_customer():
    fake = FakeDodo()
    buyer = Buyer(user_id=BUYER.user_id, email=BUYER.email, provider_customer_id="cus_1")
    run(make(fake).create_checkout(buyer, catalog(job_hunt_pass="pdt_pass")["job_hunt_pass"],
                                   return_url="https://app/return"))
    assert fake.body()["customer"] == {"customer_id": "cus_1"}


@pytest.mark.parametrize("enabled", [True, False])
def test_checkout_refuses_products_without_an_id_or_flagged_off(enabled):
    """Enabled but no product id in this mode, or an id but flagged off."""
    fake = FakeDodo()
    product = catalog(pro_monthly="pdt_pro" if not enabled else "")["pro_monthly"]
    product = product.model_copy(update={"enabled": enabled})
    with pytest.raises(ProductUnavailable):
        run(make(fake).create_checkout(BUYER, product, return_url="https://app/return"))
    assert fake.requests == []


def test_checkout_api_error_is_a_payment_error():
    with pytest.raises(PaymentError):
        run(make(FakeDodo(status=500)).create_checkout(
            BUYER, catalog(credit_pack_5="pdt_pack")["credit_pack_5"], return_url="https://app/return"))


# --- webhooks ------------------------------------------------------------------------


def envelope(type_="payment.succeeded") -> bytes:
    return json.dumps({"business_id": "bus_1", "type": type_, "timestamp": "2026-10-21T10:00:00.000Z",
                       "data": {"payload_type": "Payment", "payment_id": "pay_1"}}).encode()


def signed(body: bytes, *, secret: str = SECRET, msg_id: str = "msg_1", ts: float | None = None) -> dict:
    ts = int(time.time() if ts is None else ts)
    sig = Webhook(secret).sign(msg_id, datetime.fromtimestamp(ts, UTC), body.decode())
    return {"Webhook-Id": msg_id, "Webhook-Timestamp": str(ts), "Webhook-Signature": sig}


def test_valid_webhook_is_parsed():
    body = envelope()
    event = make(FakeDodo()).handle_webhook(body, signed(body))
    assert (event.event_id, event.type, event.data["payment_id"]) == ("msg_1", "payment.succeeded", "pay_1")
    assert event.occurred_at == datetime(2026, 10, 21, 10, 0, tzinfo=UTC)


def test_unknown_event_type_still_verifies_and_parses():
    body = envelope("something.new")
    assert make(FakeDodo()).handle_webhook(body, signed(body)).type == "something.new"


def tampered(body: bytes, headers: dict) -> tuple[bytes, dict]:
    return body.replace(b"pay_1", b"pay_2"), headers


def other_secret(body, headers):
    return body, signed(body, secret="whsec_" + base64.b64encode(b"another-secret").decode())


def stale(body, headers):
    return body, signed(body, ts=time.time() - 600)


def reserialized(body, headers):
    return json.dumps(json.loads(body), indent=2).encode(), headers


def missing_header(body, headers):
    return body, {k: v for k, v in headers.items() if k != "Webhook-Signature"}


def garbage_signature(body, headers):
    return body, {**headers, "Webhook-Signature": "not-a-signature"}


def not_utf8(body, headers):
    return b"\xff\xfe", headers


@pytest.mark.parametrize("attack", [tampered, other_secret, stale, reserialized, missing_header,
                                    garbage_signature, not_utf8])
def test_bad_webhooks_are_rejected(attack):
    body = envelope()
    bad_body, bad_headers = attack(body, signed(body))
    with pytest.raises(InvalidSignature):
        make(FakeDodo()).handle_webhook(bad_body, bad_headers)


def test_signed_but_malformed_envelope_is_a_payment_error():
    body = json.dumps({"type": "payment.succeeded"}).encode()
    with pytest.raises(PaymentError):
        make(FakeDodo()).handle_webhook(body, signed(body))


# --- customer portal -----------------------------------------------------------------


def test_portal_session_for_known_customer():
    fake = FakeDodo()
    buyer = Buyer(user_id=BUYER.user_id, email=BUYER.email, provider_customer_id="cus_1")
    assert run(make(fake).get_portal_url(buyer, return_url="https://app/account/billing")) == "https://portal/session"
    assert fake.requests[-1].url.path == "/customers/cus_1/customer-portal/session"
    assert fake.requests[-1].url.params["return_url"] == "https://app/account/billing"


def test_portal_falls_back_to_static_login_or_none():
    assert run(make(FakeDodo(), business_id="bus_1").get_portal_url(BUYER)) == \
        "https://test.customer.dodopayments.com/login/bus_1"
    assert run(make(FakeDodo()).get_portal_url(BUYER)) is None


# --- refunds -------------------------------------------------------------------------


def test_full_refund():
    fake = FakeDodo()
    result = run(make(fake).refund("pay_1", reason="Customer asked within 7 days", metadata={"by": "admin"}))
    assert (result.provider_refund_id, result.status) == ("rfd_1", "pending")
    assert fake.body() == {"payment_id": "pay_1", "reason": "Customer asked within 7 days",
                           "metadata": {"by": "admin"}}


def test_partial_refund_names_the_item():
    fake = FakeDodo()
    run(make(fake).refund("pay_1", reason="partial", amount_minor=200, item_id="pdt_pack"))
    assert fake.body()["items"] == [{"item_id": "pdt_pack", "amount": 200}]


def test_partial_refund_without_item_is_refused_locally():
    fake = FakeDodo()
    with pytest.raises(ValueError):
        run(make(fake).refund("pay_1", reason="partial", amount_minor=200))
    assert fake.requests == []


def test_refund_is_never_retried():
    fake = FakeDodo(status=500)
    provider = DodoProvider(
        api_key="k", webhook_secret=SECRET, environment="test",
        client=AsyncDodoPayments(bearer_token="k", environment="test_mode", base_url=None, max_retries=3,
                                 http_client=httpx.AsyncClient(transport=httpx.MockTransport(fake))),
    )
    with pytest.raises(PaymentError):
        run(provider.refund("pay_1", reason="x"))
    assert len(fake.requests) == 1
