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
    # Where magic-link emails go: "outbox" writes them to backend/.dev-outbox/ (dev only).
    mailer: str = field(default_factory=lambda: os.environ.get("RT_MAILER", "outbox"))
    # OAuth apps (owned by 0707Labs). A provider with either value missing shows as unavailable.
    google_client_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_SECRET", ""))
    github_client_id: str = field(default_factory=lambda: os.environ.get("GITHUB_CLIENT_ID", ""))
    github_client_secret: str = field(default_factory=lambda: os.environ.get("GITHUB_CLIENT_SECRET", ""))


def get_settings() -> Settings:
    return Settings()
