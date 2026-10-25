import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


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
    @property
    def local_origin(self) -> bool:
        """RT_PUBLIC_URL is localhost (dev, tests, e2e). Anything else is a deployment, which
        must have real secrets and real email (app.auth.signing, app.auth.mailer)."""
        return urlsplit(self.public_url).hostname in {"localhost", "127.0.0.1"}

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
    # Where magic-link emails go: "outbox" writes them to backend/.dev-outbox/ (dev only),
    # "ses" sends through Amazon SES (docs/email.md). The app refuses to start if "ses" lacks
    # a sender or keys.
    mailer: str = field(default_factory=lambda: os.environ.get("RT_MAILER", "outbox").strip().lower())
    # Sender, e.g. "Resume Tailor <no-reply@mail.example.com>"; its domain must be verified in SES.
    mail_from: str = field(default_factory=lambda: os.environ.get("RT_MAIL_FROM", "").strip())
    ses_region: str = field(default_factory=lambda: os.environ.get("RT_SES_REGION", "ap-south-1").strip())
    # Optional SES configuration set (bounce/complaint events, suppression overrides).
    ses_configuration_set: str = field(default_factory=lambda: os.environ.get("RT_SES_CONFIGURATION_SET", "").strip())
    # An IAM user allowed only ses:SendEmail on the sender identity. Session token: temporary creds only.
    aws_access_key_id: str = field(default_factory=lambda: os.environ.get("AWS_ACCESS_KEY_ID", ""))
    aws_secret_access_key: str = field(default_factory=lambda: os.environ.get("AWS_SECRET_ACCESS_KEY", ""))
    aws_session_token: str = field(default_factory=lambda: os.environ.get("AWS_SESSION_TOKEN", ""))
    # Optional error reporting (app/observability.py): off unless SENTRY_DSN is set. Environment
    # and release default to Railway's own variables; tracing is off unless a rate is given.
    sentry_dsn: str = field(default_factory=lambda: os.environ.get("SENTRY_DSN", "").strip())
    sentry_environment: str = field(default_factory=lambda: (
        os.environ.get("SENTRY_ENVIRONMENT") or os.environ.get("RAILWAY_ENVIRONMENT_NAME") or "development").strip())
    sentry_release: str = field(default_factory=lambda: (
        os.environ.get("SENTRY_RELEASE") or os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "").strip())
    sentry_traces_sample_rate: float = field(
        default_factory=lambda: min(max(float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE") or 0), 0.0), 1.0)
    )
    # Optional Slack incoming webhook for budget alerts (https://hooks.slack.com/... only).
    slack_webhook_url: str = field(default_factory=lambda: os.environ.get("RT_SLACK_WEBHOOK_URL", "").strip())
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
