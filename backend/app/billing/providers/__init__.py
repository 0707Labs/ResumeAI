"""Payment providers behind one interface. get_payment_provider() builds the active one
from settings, or raises ProviderNotConfigured (callers answer 503, never fall back)."""

from functools import lru_cache

from app.billing.providers.base import PaymentProvider, ProviderNotConfigured
from app.config import get_settings


@lru_cache
def get_payment_provider() -> PaymentProvider:
    from app.billing.providers.dodo import DodoProvider

    s = get_settings()
    return DodoProvider(
        api_key=s.dodo_api_key,
        webhook_secret=s.dodo_webhook_secret,
        environment=s.dodo_environment,
        business_id=s.dodo_business_id,
    )


__all__ = ["PaymentProvider", "ProviderNotConfigured", "get_payment_provider"]
