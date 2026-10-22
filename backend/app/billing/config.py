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
    # Tailorings a user may start each calendar month (UTC) with nothing else. Downloads
    # are always paid.
    analyses_per_month: Annotated[int, Field(ge=0)]


class Analyses(_Strict):
    # How long a started analysis may use Claude.
    usable_hours: PositiveInt = 24
    # Analyses per user per UTC day that may use Claude; later ones that day run
    # rules-only (they still start, and still download). 0 turns Claude off.
    claude_analyses_per_day: Annotated[int, Field(ge=0)] = 10
    # The same, for a user with an active pass or Pro.
    paid_claude_analyses_per_day: Annotated[int, Field(ge=0)] = 30


class Downloads(_Strict):
    # Credits one clean download spends when no pass or Pro covers it. Past the free
    # tailorings, starting one needs what a download would (it spends nothing).
    credits_per_download: PositiveInt = 1
    # Re-downloading the same tailored resume is free this long after a paid download.
    redownload_free_days: Annotated[int, Field(ge=0)] = 7
    # Signed download links stop working after this.
    url_ttl_seconds: Annotated[int, Field(ge=10, le=3600)] = 120


class Retention(_Strict):
    # Resume text is kept only this long; `python -m app.billing.cli purge-expired` clears it
    # (app.billing.retention). An analysis's resume, job description and tailoring go this
    # many days after its last download, or after it started if it was never downloaded.
    analysis_days: PositiveInt = 30
    # A download's final resume (what its signed link renders) goes this many days after
    # the download. Unset: the re-download window ([downloads].redownload_free_days, at least 1).
    download_days: PositiveInt | None = None
    batch_size: Annotated[int, Field(ge=1, le=10_000)] = 500  # rows per purge transaction


class Referrals(_Strict):
    enabled: bool = True
    # When the referrer earns the reward: once the friend's account exists (their email is
    # verified by then), or once they finish their first tailoring.
    trigger: Literal["on_verified_signup", "on_first_tailoring"] = "on_first_tailoring"
    reward_credits: PositiveInt = 1
    invitee_reward_credits: Annotated[int, Field(ge=0)] = 0
    monthly_cap: PositiveInt = 10  # rewards per referrer per calendar month (UTC)
    # In invite-only mode a referral link also works as an invite, this many times per user.
    invites_per_user: Annotated[int, Field(ge=0)] = 5
    # Referred sign-ups from one network (IP) within review_window_hours: from this many on,
    # each new one waits in the admin queue instead of paying out.
    same_ip_review_threshold: PositiveInt = 3
    review_window_hours: PositiveInt = 24
    extra_disposable_domains: list[str] = []


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
    analyses: Analyses = Analyses()
    downloads: Downloads = Downloads()
    referrals: Referrals = Referrals()
    retention: Retention = Retention()
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

    @model_validator(mode="after")
    def _retention_outlives_its_uses(self) -> "BillingConfig":
        # A re-download in the window is rendered from the analysis, and Claude may be used
        # until usable_until, so the analysis text must outlast both.
        if self.retention.analysis_days < self.downloads.redownload_free_days:
            raise ValueError("[retention].analysis_days must be at least [downloads].redownload_free_days")
        if self.retention.analysis_days * 24 <= self.analyses.usable_hours:
            raise ValueError("[retention].analysis_days must be longer than [analyses].usable_hours")
        return self

    @property
    def download_retention_days(self) -> int:
        """Days a download's final resume is kept."""
        return self.retention.download_days or max(self.downloads.redownload_free_days, 1)

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
