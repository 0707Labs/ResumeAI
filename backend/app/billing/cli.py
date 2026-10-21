"""Billing admin commands.

    python -m app.billing.cli check-alerts
    python -m app.billing.cli adjust-credits USER_ID DELTA --note "why" [--key KEY]
    python -m app.billing.cli sweep-analyses

check-alerts prints current alerts (failing webhooks, daily LLM spend over the threshold,
unpriced models) and exits 1 if there are any, so a cron job can notify on it.

adjust-credits writes an 'admin_adjust' ledger row (positive adds, negative takes back,
never below zero). The note is required and kept on the row; --key makes a retry safe
(default: a fresh key, so running it twice adjusts twice).

sweep-analyses releases analyses left unfinished past usable_until and refunds their
credits, once. Run it from cron (hourly is plenty); a user's own stale runs are also
released when they next start one.
"""

import argparse
import asyncio
import sys
import uuid

from app.billing import analyses, ledger
from app.billing.admin import alerts
from app.billing.config import get_billing_config
from app.db.session import get_engine, get_sessionmaker


async def check_alerts() -> int:
    try:
        async with get_sessionmaker()() as db:
            found = await alerts(db, get_billing_config())
    finally:
        await get_engine().dispose()
    for a in found:
        print(f"[{a.severity.upper()}] {a.kind}: {a.message}")
    if not found:
        print("No billing alerts.")
    return 1 if found else 0


async def adjust_credits(user_id: uuid.UUID, delta: int, note: str, key: str) -> int:
    try:
        async with get_sessionmaker()() as db, db.begin():
            posted = await ledger.post(db, user_id, delta, reason="admin_adjust", idempotency_key=key, note=note)
    except ledger.LedgerError as exc:
        print(f"Not adjusted: {exc.__class__.__name__}: {exc}")
        return 1
    finally:
        await get_engine().dispose()
    print(f"{'Adjusted' if posted.applied else 'Already applied'}: {posted.delta:+d}, balance now {posted.balance} "
          f"(key {key})")
    return 0


async def sweep_analyses() -> int:
    try:
        async with get_sessionmaker()() as db, db.begin():
            released = await analyses.sweep(db)
    finally:
        await get_engine().dispose()
    print(f"Released {released} abandoned analys{'is' if released == 1 else 'es'}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.billing.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-alerts", help="print billing alerts; exit 1 if any")
    sub.add_parser("sweep-analyses", help="refund credits of analyses abandoned past usable_until")
    adj = sub.add_parser("adjust-credits", help="add or take back credits with a note")
    adj.add_argument("user_id", type=uuid.UUID)
    adj.add_argument("delta", type=int)
    adj.add_argument("--note", required=True)
    adj.add_argument("--key", help="idempotency key (reuse it to retry safely)")
    args = parser.parse_args(argv)
    if args.command == "check-alerts":
        return asyncio.run(check_alerts())
    if args.command == "sweep-analyses":
        return asyncio.run(sweep_analyses())
    if args.command == "adjust-credits":
        if args.delta == 0 or not args.note.strip():
            parser.error("delta must be non-zero and the note non-empty")
        return asyncio.run(adjust_credits(args.user_id, args.delta, args.note.strip(),
                                          args.key or f"admin:{uuid.uuid4()}"))
    return 2


if __name__ == "__main__":
    sys.exit(main())
