"""Billing admin commands.

    python -m app.billing.cli check-alerts

Prints current alerts (failing webhooks, daily LLM spend over the threshold, unpriced
models) and exits 1 if there are any, so a cron job or uptime monitor can notify on it.
"""

import argparse
import asyncio
import sys

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.billing.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-alerts", help="print billing alerts; exit 1 if any")
    args = parser.parse_args(argv)
    if args.command == "check-alerts":
        return asyncio.run(check_alerts())
    return 2


if __name__ == "__main__":
    sys.exit(main())
