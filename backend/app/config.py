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
    # Postgres via psycopg 3. The app connects lazily, so the rules-only pipeline
    # (and the e2e run) still starts without a database.
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "RT_DATABASE_URL", "postgresql+psycopg:///resume_tailor"
        )
    )
    # Signs short-lived cookies (OAuth state, pending sign-up). Required outside dev.
    auth_secret: str = field(default_factory=lambda: os.environ.get("RT_AUTH_SECRET", ""))
    # Base for OAuth redirect URIs and the CSRF Origin check.
    public_url: str = field(
        default_factory=lambda: os.environ.get("RT_PUBLIC_URL", "http://localhost:3000").rstrip("/")
    )
    # Invite-only mode: new accounts need an invite (on by default). Off = open signup;
    # an invite typed anyway is still checked and used up.
    invite_only: bool = field(
        default_factory=lambda: os.environ.get("RT_INVITE_ONLY", "1").strip().lower() not in {"0", "false", "off", "no"}
    )
    # Local end-to-end runs only: multiply every rate limit by this. Ignored (1) unless
    # RT_PUBLIC_URL is a localhost origin, so it can't loosen a deployed instance.
    dev_rate_limit_scale: int = field(
        default_factory=lambda: max(1, min(int(os.environ.get("RT_DEV_RATE_LIMIT_SCALE", "1") or 1), 100))
    )
    # Where magic-link emails go: "outbox" writes them to backend/.dev-outbox/ (dev only).
    mailer: str = field(default_factory=lambda: os.environ.get("RT_MAILER", "outbox"))
    # OAuth apps (owned by 0707Labs). A provider with either value missing shows as unavailable.
    google_client_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_SECRET", ""))
    github_client_id: str = field(default_factory=lambda: os.environ.get("GITHUB_CLIENT_ID", ""))
    github_client_secret: str = field(default_factory=lambda: os.environ.get("GITHUB_CLIENT_SECRET", ""))
    # Dodo Payments (merchant of record). Passed to the SDK explicitly: its own env vars
    # (DODO_PAYMENTS_*) are not used, and it would default to live mode.
    dodo_api_key: str = field(default_factory=lambda: os.environ.get("DODO_API_KEY", ""))
    dodo_webhook_secret: str = field(default_factory=lambda: os.environ.get("DODO_WEBHOOK_SECRET", ""))
    # "test" or "live"; anything else is refused when the provider is built.
    dodo_environment: str = field(
        default_factory=lambda: os.environ.get("DODO_ENVIRONMENT", "test").strip().lower()
    )
    # Optional: the static customer-portal login link for buyers we have no Dodo customer id for.
    dodo_business_id: str = field(default_factory=lambda: os.environ.get("DODO_BUSINESS_ID", ""))


def get_settings() -> Settings:
    return Settings()
