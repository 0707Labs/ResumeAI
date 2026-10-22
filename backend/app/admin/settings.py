"""Runtime settings: switches staff can flip without a deploy.

Each key has a type and a default taken from env/billing.toml, so the app behaves exactly
as before until someone changes a value. A stored value overrides the default; deleting
it (reset) falls back again. Every change goes through `write()`, which audits it in the
same transaction. Prices, credit amounts and pass lengths stay in billing.toml (purchases
snapshot them) and are view-only.

app_settings has no grant for rt_app, so readers inside a signed-in request use
`service_scope` (read_all does that itself).
"""

from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import audit
from app.billing.config import BillingConfig, get_billing_config
from app.config import get_settings
from app.db.models import AppSetting, User
from app.db.rls import service_scope
from app.db.session import get_db


class Settings(BaseModel):
    """Every runtime setting, with its type. Unknown keys are refused."""

    model_config = ConfigDict(extra="forbid")

    invite_only: bool
    analyses_paused: bool = False  # kill switch: no new analyses (in-flight ones finish)
    maintenance_banner: str | None = Field(default=None, max_length=280)
    # Invites and referrals (defaults: billing.toml [referrals] and [signup]).
    invites_per_user: int = Field(ge=0, le=100)
    signup_bonus_credits: int = Field(ge=0, le=100)
    referrals_enabled: bool
    referral_trigger: Literal["on_verified_signup", "on_first_tailoring"]
    referral_reward_credits: int = Field(ge=0, le=50)
    referral_monthly_cap: int = Field(ge=0, le=1000)
    # Claude spend (defaults: billing.toml [alerts].daily_llm_spend_usd, monthly = 30 x daily).
    daily_budget_usd: float = Field(gt=0, le=1_000_000)
    monthly_budget_usd: float = Field(gt=0, le=10_000_000)
    budget_kill_switch: bool = True  # past a budget, new analyses pause until it resets


def defaults(base: BillingConfig | None = None) -> dict[str, Any]:
    config = base or get_billing_config()
    return {
        "invite_only": get_settings().invite_only, "analyses_paused": False, "maintenance_banner": None,
        "invites_per_user": config.referrals.invites_per_user, "signup_bonus_credits": config.signup.bonus_credits,
        "referrals_enabled": config.referrals.enabled, "referral_trigger": config.referrals.trigger,
        "referral_reward_credits": config.referrals.reward_credits, "referral_monthly_cap": config.referrals.monthly_cap,
        "daily_budget_usd": config.alerts.daily_llm_spend_usd, "monthly_budget_usd": config.alerts.daily_llm_spend_usd * 30,
        "budget_kill_switch": True,
    }


@dataclass(frozen=True)
class Current:
    values: Settings
    overridden: frozenset[str]  # keys with a stored value


async def read_all(db: AsyncSession, base: BillingConfig | None = None) -> Current:
    async with service_scope(db):
        rows = (await db.execute(select(AppSetting.key, AppSetting.value))).all()
    stored = {k: v for k, v in rows if k in Settings.model_fields}  # a retired key is ignored
    return Current(values=Settings(**{**defaults(base), **stored}), overridden=frozenset(stored))


def apply(base: BillingConfig, values: Settings) -> BillingConfig:
    """billing.toml with the runtime overrides that live in it (referrals, sign-up credits)."""
    return base.model_copy(update={
        "referrals": base.referrals.model_copy(update={
            "enabled": values.referrals_enabled, "trigger": values.referral_trigger,
            "reward_credits": values.referral_reward_credits, "monthly_cap": values.referral_monthly_cap,
            "invites_per_user": values.invites_per_user}),
        "signup": base.signup.model_copy(update={"bonus_credits": values.signup_bonus_credits}),
    })


async def live_config(db: AsyncSession, base: BillingConfig | None = None) -> BillingConfig:
    base = base or get_billing_config()
    return apply(base, (await read_all(db, base)).values)


async def invite_only(db: AsyncSession) -> bool:
    return (await read_all(db)).values.invite_only


async def live_billing_config(base: BillingConfig = Depends(get_billing_config),
                              db: AsyncSession = Depends(get_db)) -> BillingConfig:
    """FastAPI dependency: billing.toml plus the settings staff changed at runtime."""
    return await live_config(db, base)


class UnknownSetting(ValueError):
    pass


async def write(db: AsyncSession, actor: User, request: Request | None, key: str, value: Any,
                reason: str) -> Current:
    """Store one setting, validated against Settings, audited. Commits.
    To go back to the env/billing.toml default, use reset()."""
    if key not in Settings.model_fields:
        raise UnknownSetting(key)
    before = await read_all(db)
    try:
        checked = Settings(**{**before.values.model_dump(), key: value})
    except ValidationError as exc:
        raise ValueError(exc.errors()[0]["msg"]) from None
    new_value = getattr(checked, key)
    await db.execute(insert(AppSetting).values(key=key, value=new_value, updated_by=actor.id)
                     .on_conflict_do_update(index_elements=[AppSetting.key],
                                            set_={"value": new_value, "updated_by": actor.id,
                                                  "updated_at": func.now()}))
    audit.record(db, actor, "settings.update", request=request, target_type="setting", target_id=key,
                 reason=reason, before={key: getattr(before.values, key)}, after={key: new_value})
    await db.commit()
    return await read_all(db)


async def reset(db: AsyncSession, actor: User, request: Request | None, key: str, reason: str) -> Current:
    """Drop the stored value so the env/billing.toml default applies again. Commits."""
    if key not in Settings.model_fields:
        raise UnknownSetting(key)
    before = await read_all(db)
    await db.execute(delete(AppSetting).where(AppSetting.key == key))
    audit.record(db, actor, "settings.reset", request=request, target_type="setting", target_id=key,
                 reason=reason, before={key: getattr(before.values, key)}, after={key: defaults()[key]})
    await db.commit()
    return await read_all(db)
