"""Send a signed, Dodo-shaped webhook to the local backend (test mode only).

`dodo wh trigger` sends unsigned mocks, which our endpoint rightly rejects. This signs
events with DODO_WEBHOOK_SECRET the way Dodo does (Standard Webhooks), so the full
path runs: signature check, idempotency, ledger. Use it when you don't want to pay
through a real test checkout, or to replay and race deliveries.

    cd backend
    # Pretend checkout <our payment id> was paid (reads the row for its session/product/user):
    .venv/bin/python scripts/dodo_send_webhook.py payment.succeeded --payment-row <uuid>
    # Refund / dispute it (Dodo payment id defaults to pay_test_<first 8 of row id>):
    .venv/bin/python scripts/dodo_send_webhook.py refund.succeeded --payment-row <uuid> [--partial 200]
    .venv/bin/python scripts/dodo_send_webhook.py dispute.lost --payment-row <uuid>
    # Send the same delivery twice (replay):  --msg-id msg_1  on both calls

Refuses to run unless DODO_ENVIRONMENT=test.
"""

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


def _load_dotenv() -> None:
    env = BACKEND / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


def payment_row(payment_id: str) -> dict:
    from sqlalchemy import create_engine, text

    from app.config import get_settings

    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT id, user_id, product_key, provider_checkout_id, provider_payment_id, snapshot,"
                " amount_minor, currency FROM payments WHERE id = :i"), {"i": payment_id}).mappings().first()
    finally:
        engine.dispose()
    if row is None:
        sys.exit(f"No payment {payment_id} in the database.")
    return dict(row)


def build(event_type: str, row: dict, args) -> dict:
    pay_id = row["provider_payment_id"] or f"pay_test_{str(row['id'])[:8]}"
    if event_type.startswith("payment."):
        amount = args.amount or 600
        return {
            "payload_type": "Payment", "payment_id": pay_id, "checkout_session_id": row["provider_checkout_id"],
            "status": event_type.split(".")[1], "metadata": {"user_id": str(row["user_id"]), "product_key": row["product_key"]},
            "customer": {"customer_id": "cus_test_local", "email": "test@example.com", "name": "Test Buyer"},
            "total_amount": amount, "tax": round(amount * 0.153), "currency": args.currency,
            "settlement_amount": amount, "settlement_currency": "USD", "settlement_tax": round(amount * 0.153),
            "product_cart": [{"product_id": row["snapshot"].get("provider_product_id"), "quantity": 1}],
            "subscription_id": None,
        }
    if event_type.startswith("refund."):
        return {"payload_type": "Refund", "refund_id": args.refund_id or f"rfd_test_{uuid.uuid4().hex[:8]}",
                "payment_id": pay_id, "is_partial": args.partial is not None, "amount": args.partial,
                "currency": row["currency"] or args.currency, "status": event_type.split(".")[1]}
    if event_type.startswith("dispute."):
        return {"payload_type": "Dispute", "dispute_id": args.dispute_id or f"dsp_test_{str(row['id'])[:8]}",
                "payment_id": pay_id, "amount": "6.00", "currency": "USD", "dispute_stage": "dispute",
                "dispute_status": event_type.split(".")[1]}
    sys.exit(f"Unsupported event type {event_type}; use payment.*, refund.* or dispute.*")


def main() -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("event_type")
    p.add_argument("--payment-row", required=True, help="our payments.id")
    p.add_argument("--msg-id", help="webhook-id to send (reuse it to replay a delivery)")
    p.add_argument("--amount", type=int, help="total_amount in minor units (default 600)")
    p.add_argument("--currency", default="USD")
    p.add_argument("--partial", type=int, help="refund amount for a partial refund")
    p.add_argument("--refund-id")
    p.add_argument("--dispute-id")
    p.add_argument("--url", default="http://localhost:8000/api/billing/webhooks/dodo")
    args = p.parse_args()

    if os.environ.get("DODO_ENVIRONMENT", "test").strip().lower() != "test":
        sys.exit("Refusing: DODO_ENVIRONMENT is not 'test'.")
    secret = os.environ.get("DODO_WEBHOOK_SECRET")
    if not secret:
        sys.exit("Set DODO_WEBHOOK_SECRET (backend/.env).")

    import httpx
    from standardwebhooks import Webhook

    body = json.dumps({"business_id": "bus_test_local", "type": args.event_type,
                       "timestamp": datetime.now(UTC).isoformat(),
                       "data": build(args.event_type, payment_row(args.payment_row), args)})
    msg_id = args.msg_id or f"msg_test_{uuid.uuid4().hex}"
    now = datetime.now(UTC)
    headers = {"webhook-id": msg_id, "webhook-timestamp": str(int(now.timestamp())),
               "webhook-signature": Webhook(secret).sign(msg_id, now, body), "content-type": "application/json"}
    res = httpx.post(args.url, content=body, headers=headers, timeout=30)
    print(f"{args.event_type} {msg_id} -> {res.status_code} {res.text}")
    return 0 if res.is_success else 1


if __name__ == "__main__":
    sys.exit(main())
