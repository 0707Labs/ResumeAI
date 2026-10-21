"""LLM cost tracking: price each Claude call from billing.toml and store one llm_usage row.

The pipeline routes are synchronous and work without a database, so recording uses a
small sync engine and never raises: a missing or slow database loses a usage row,
not the person's analysis.
"""

import contextvars
import logging
import uuid
from decimal import Decimal
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, insert

from app.billing.config import BillingConfig, get_billing_config
from app.config import get_settings
from app.db.models import LlmUsage

log = logging.getLogger("app.billing")

# The browser's id for the analysis being worked on (X-Analysis-Id), set per request.
current_analysis_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "current_analysis_id", default=None
)

MILLION = Decimal(1_000_000)


def parse_analysis_id(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def cost_usd(config: BillingConfig, model: str, *, input_tokens: int, output_tokens: int,
             cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> Decimal | None:
    """None when the model has no price in billing.toml (shown as unpriced, never as free)."""
    price = config.llm_prices.get(model)
    if price is None:
        return None
    total = (Decimal(str(price.input)) * input_tokens + Decimal(str(price.output)) * output_tokens
             + Decimal(str(price.cache_read)) * cache_read_tokens
             + Decimal(str(price.cache_write)) * cache_write_tokens)
    return (total / MILLION).quantize(Decimal("0.000001"))


@lru_cache
def _engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=2,
                         connect_args={"connect_timeout": 3})


def usage_row(stage: str, response: Any, config: BillingConfig | None = None) -> dict:
    """Token counts from an Anthropic response; the model is the one that actually answered."""
    usage = response.usage
    tokens = {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }
    model = str(getattr(response, "model", "") or "unknown")
    return {"analysis_id": current_analysis_id.get(), "stage": stage, "model": model, **tokens,
            "cost_usd": cost_usd(config or get_billing_config(), model, **tokens)}


def record_llm_usage(stage: str, response: Any) -> None:
    """Called by the LLM client after every Claude response, including refusals."""
    try:
        row = usage_row(stage, response)
        if row["cost_usd"] is None:
            log.warning("no price for model %s in billing.toml; usage recorded without cost", row["model"])
        with _engine().begin() as conn:
            conn.execute(insert(LlmUsage).values(**row))
    except Exception as exc:  # noqa: BLE001 - cost tracking must never break an analysis
        log.warning("could not record LLM usage: %s", exc.__class__.__name__)
