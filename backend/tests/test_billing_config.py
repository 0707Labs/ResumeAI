"""The billing catalog: the shipped billing.toml is valid, and bad shapes fail loudly."""

import tomllib

import pytest
from pydantic import ValidationError

from app.billing.config import DEFAULT_PATH, BillingConfig, load_billing_config


def raw() -> dict:
    with open(DEFAULT_PATH, "rb") as f:
        return tomllib.load(f)


def test_shipped_catalog_loads():
    config = load_billing_config()
    pack, pass_ = config.products["credit_pack_5"], config.products["job_hunt_pass"]
    assert (pack.kind, pack.billing, pack.credits) == ("credit_pack", "one_time", 5)
    assert (pass_.kind, pass_.billing, pass_.pass_days, pass_.fair_use_cap) == ("pass", "one_time", 30, 40)
    assert config.products["pro_monthly"].billing == "subscription"


def test_pro_is_flagged_off_by_default_and_can_be_enabled():
    assert load_billing_config().product("pro_monthly") is None
    assert load_billing_config(pro_enabled=True).product("pro_monthly") is not None


def test_unknown_product_is_unavailable():
    assert load_billing_config().product("credit_pack_500") is None


def test_product_ids_resolve_per_mode():
    data = raw()
    data["products"]["credit_pack_5"]["dodo_product_id"] = {"test": "pdt_test", "live": "pdt_live"}
    ids = BillingConfig.model_validate(data).products["credit_pack_5"].dodo_product_id
    assert (ids.for_mode("test"), ids.for_mode("live")) == ("pdt_test", "pdt_live")


@pytest.mark.parametrize("product, change", [
    ("credit_pack_5", {"credits": None}),                    # a pack without credits
    ("credit_pack_5", {"billing": "subscription"}),          # one-time product billed as a subscription
    ("job_hunt_pass", {"pass_days": None}),                  # a pass without a length
    ("job_hunt_pass", {"credits": 5}),                       # credits on a pass
    ("pro_monthly", {"interval": None}),                     # a subscription without an interval
    ("credit_pack_5", {"prices": {"INR": 0}}),               # free isn't a price
    ("credit_pack_5", {"prices": {"EUR": 500}}),             # unsupported currency
    ("credit_pack_5", {"price": 500}),                       # typo'd key
])
def test_invalid_products_are_rejected(product, change):
    data = raw()
    entry = data["products"][product]
    for key, value in change.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    with pytest.raises(ValidationError):
        BillingConfig.model_validate(data)
