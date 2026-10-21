"""Check the Dodo products named in billing.toml against the Dodo dashboard.

    cd backend && .venv/bin/python scripts/dodo_check_products.py

Uses DODO_API_KEY and DODO_ENVIRONMENT (test|live) from the environment or backend/.env,
and reads products only. For each enabled product it checks: the product id is set for
this mode and exists; one-time vs subscription matches; the base price, and any
localized price, equals the price in billing.toml; and prices are tax-inclusive when
[display].prices_include_tax says so. Exits 1 on any mismatch, so it can gate a deploy.
"""

import os
import sys
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


def check(client, config, mode: str) -> list[str]:
    from dodopayments import NotFoundError

    problems: list[str] = []
    for product in config.products.values():
        if not product.enabled:
            print(f"- {product.key}: flagged off, skipped")
            continue
        pid = product.dodo_product_id.for_mode(mode)
        if not pid:
            problems.append(f"{product.key}: no {mode} product id in billing.toml")
            continue
        try:
            remote = client.products.retrieve(pid)
        except NotFoundError:
            problems.append(f"{product.key}: {pid} not found in {mode} mode")
            continue
        price = remote.price
        if remote.is_recurring != (product.billing == "subscription"):
            problems.append(f"{product.key}: Dodo says recurring={remote.is_recurring}, billing.toml says {product.billing}")
        if config.display.prices_include_tax and not getattr(price, "tax_inclusive", False):
            problems.append(f"{product.key}: price is not tax-inclusive in Dodo, but the pricing page says it is")
        actual = {str(price.currency): getattr(price, "price", None)}
        for rule in client.products.localized_prices.list(pid).items:
            if rule.country_code is None:
                actual[str(rule.currency)] = rule.amount
        for currency, amount in product.prices.items():
            if actual.get(currency) != amount:
                problems.append(f"{product.key}: {currency} is {actual.get(currency)} in Dodo, {amount} in billing.toml")
        print(f"- {product.key}: {pid} checked ({', '.join(f'{c} {a}' for c, a in actual.items())})")
    return problems


def main() -> int:
    _load_dotenv()
    from dodopayments import DodoPayments

    from app.billing.config import get_billing_config

    mode = os.environ.get("DODO_ENVIRONMENT", "test").strip().lower()
    if mode not in ("test", "live") or not os.environ.get("DODO_API_KEY"):
        print("Set DODO_API_KEY and DODO_ENVIRONMENT=test|live (backend/.env).")
        return 2
    client = DodoPayments(bearer_token=os.environ["DODO_API_KEY"], base_url=None,
                          environment="test_mode" if mode == "test" else "live_mode")
    problems = check(client, get_billing_config(), mode)
    for p in problems:
        print(f"MISMATCH {p}")
    print("All products match billing.toml." if not problems else f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
