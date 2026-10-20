import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
            if o.strip()
        ]
    )
    # Read by the anthropic SDK itself; we only check presence for /health.
    llm_configured: bool = field(
        default_factory=lambda: bool(os.environ.get("ANTHROPIC_API_KEY"))
    )


def get_settings() -> Settings:
    return Settings()
