"""The billing catalog (backend/billing.toml), validated with pydantic.

Every product fact (Dodo product IDs, prices, credits, pass length, fair-use caps)
and the fee estimates come from here; handlers and providers never hard-code them.
"""

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "billing.toml"

Currency = Literal["INR", "USD"]
Mode = Literal["test", "live"]
PositiveInt = Annotated[int, Field(gt=0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderProductIds(_Strict):
    test: str = ""
    live: str = ""

    def for_mode(self, mode: Mode) -> str:
        return self.test if mode == "test" else self.live


class Product(_Strict):
    key: str
    kind: Literal["credit_pack", "pass", "subscription"]
    name: str
    billing: Literal["one_time", "subscription"]
    prices: dict[Currency, PositiveInt]
    dodo_product_id: ProviderProductIds
    enabled: bool = True
    credits: PositiveInt | None = None
    pass_days: PositiveInt | None = None
    fair_use_cap: PositiveInt | None = None
    interval: Literal["month", "year"] | None = None

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> "Product":
        expected_billing = "subscription" if self.kind == "subscription" else "one_time"
        if self.billing != expected_billing:
            raise ValueError(f"{self.key}: kind {self.kind} must bill as {expected_billing}")
        if (self.kind == "credit_pack") != (self.credits is not None):
            raise ValueError(f"{self.key}: credits is required for, and only for, credit packs")
        if self.kind == "pass" and (self.pass_days is None or self.fair_use_cap is None):
            raise ValueError(f"{self.key}: a pass needs pass_days and fair_use_cap")
        if self.kind != "pass" and self.pass_days is not None:
            raise ValueError(f"{self.key}: pass_days is only for passes")
        if self.kind == "subscription" and (self.interval is None or self.fair_use_cap is None):
            raise ValueError(f"{self.key}: a subscription needs interval and fair_use_cap")
        if not self.prices:
            raise ValueError(f"{self.key}: at least one price is required")
        return self


class Free(_Strict):
    analyses_per_month: Annotated[int, Field(ge=0)]


class Display(_Strict):
    prices_include_tax: bool


class Signup(_Strict):
    bonus_credits: Annotated[int, Field(ge=0)] = 0


class DodoFees(_Strict):
    base_pct: Annotated[float, Field(ge=0)]
    base_fixed_usd_cents: Annotated[int, Field(ge=0)]
    international_extra_pct: Annotated[float, Field(ge=0)]
    india_pct: Annotated[float, Field(ge=0)]
    india_fixed_usd_cents: Annotated[int, Field(ge=0)]
    subscription_extra_pct: Annotated[float, Field(ge=0)]
    refund_fixed_usd_cents: Annotated[int, Field(ge=0)]
    dispute_fixed_usd_cents: Annotated[int, Field(ge=0)]
    settlement_is_net_of_fees: bool = False


class Fees(_Strict):
    dodo: DodoFees


class Alerts(_Strict):
    webhook_failures: PositiveInt
    daily_llm_spend_usd: Annotated[float, Field(gt=0)]


class LlmPrice(_Strict):
    """USD per million tokens."""

    input: Annotated[float, Field(ge=0)]
    output: Annotated[float, Field(ge=0)]
    cache_read: Annotated[float, Field(ge=0)]
    cache_write: Annotated[float, Field(ge=0)]


class BillingConfig(_Strict):
    version: PositiveInt
    display: Display
    free: Free
    signup: Signup
    products: dict[str, Product]
    fees: Fees
    alerts: Alerts
    llm_prices: dict[str, LlmPrice]

    @model_validator(mode="before")
    @classmethod
    def _key_products(cls, data: dict) -> dict:
        products = data.get("products")
        if isinstance(products, dict):
            data = {**data, "products": {k: {"key": k, **v} for k, v in products.items()}}
        return data

    def product(self, key: str) -> Product | None:
        """The product a buyer may purchase now, or None (unknown or flagged off)."""
        product = self.products.get(key)
        return product if product is not None and product.enabled else None


def load_billing_config(path: Path | str = DEFAULT_PATH, *, pro_enabled: bool | None = None) -> BillingConfig:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    if pro_enabled is not None and "pro_monthly" in data.get("products", {}):
        data["products"]["pro_monthly"]["enabled"] = pro_enabled
    return BillingConfig.model_validate(data)


def _env_flag(name: str) -> bool | None:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return None
    return value in ("1", "true", "yes", "on")


@lru_cache
def get_billing_config() -> BillingConfig:
    return load_billing_config(
        os.environ.get("RT_BILLING_CONFIG", DEFAULT_PATH),
        pro_enabled=_env_flag("RT_BILLING_PRO_ENABLED"),
    )
