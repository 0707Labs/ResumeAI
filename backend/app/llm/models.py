"""Which model, token cap and effort each pipeline step uses (runtime setting llm_models,
edited in /admin/integrations by a superadmin).

The client runs in a worker thread, so this reads app_settings through the same small
sync engine the cost recorder uses, cached for CACHE_SECONDS. Anything wrong (no
database, a bad value, a model without a price) falls back to the built-in default, so a
setting can never stop analyses.
"""

import logging
import threading
import time

from sqlalchemy import text

from app.admin.settings import StepModel

log = logging.getLogger(__name__)

CACHE_SECONDS = 30.0
_lock = threading.Lock()
_cache: tuple[float, dict[str, StepModel]] = (float("-inf"), {})


def _load() -> dict[str, StepModel]:
    from app.billing.config import get_billing_config
    from app.billing.costs import _engine

    with _engine().connect() as conn:
        raw = conn.execute(text("SELECT value FROM app_settings WHERE key = 'llm_models'")).scalar()
    priced = get_billing_config().llm_prices
    out: dict[str, StepModel] = {}
    for step, value in (raw or {}).items():
        try:
            chosen = StepModel.model_validate(value)
        except ValueError:
            continue
        if chosen.model in priced:
            out[step] = chosen
    return out


def for_step(step: str) -> StepModel | None:
    """The configured model for a pipeline step, or None for the built-in default."""
    global _cache
    now = time.monotonic()
    with _lock:
        loaded_at, models = _cache
        if now - loaded_at >= CACHE_SECONDS:
            try:
                models = _load()
            except Exception as exc:  # noqa: BLE001 - fall back to the default model
                log.warning("could not read llm_models: %s", exc.__class__.__name__)
                models = {}
            _cache = (now, models)
    return models.get(step)


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = (float("-inf"), {})
