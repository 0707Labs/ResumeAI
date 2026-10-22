"""Auth event log. One JSON line per event on the "app.auth.events" logger.

Carries user_id at most: never an email, IP, name, code, token or provider
account id. `reason` is a short machine code from the calling flow, not free text."""

import json
import logging
import uuid
from typing import Literal

log = logging.getLogger("app.auth.events")

AuthEvent = Literal[
    "login",
    "logout",
    "session_expired",
    "csrf_rejected",
    "rate_limited",
    "magic_link_sent",
    "magic_link_failed",
    "magic_link_used",
    "pending_created",
    "account_linked_auto",
    "account_unavailable",
    "invite_checked",
    "signup_completed",
    "signup_failed",
    "waitlist_joined",
    "oauth_started",
    "oauth_failed",
    "account_linked",
    "account_unlinked",
    "account_link_failed",
    "account_deleted",
    "data_exported",
]


def log_auth_event(
    event: AuthEvent,
    *,
    outcome: Literal["ok", "denied", "error"] = "ok",
    user_id: uuid.UUID | None = None,
    provider: Literal["google", "github", "email"] | None = None,
    reason: str | None = None,
) -> None:
    record = {"event": event, "outcome": outcome}
    if user_id is not None:
        record["user_id"] = str(user_id)
    if provider is not None:
        record["provider"] = provider
    if reason is not None:
        record["reason"] = reason
    log.info(json.dumps(record, sort_keys=True))
