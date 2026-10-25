"""Optional error reporting to Sentry, off unless SENTRY_DSN is set.

Resumes and job descriptions are the most sensitive data we hold, and sign-in links and
session cookies are credentials. So an event says *where* something failed, never *what*
anyone sent. Rather than hunting for sensitive fields (resume text also hides in pydantic
error messages, parser exceptions, local variables, log arguments and CLI arguments), every
event is rebuilt from an allowlist (`scrub`):

- request: method and path only. No body, headers, cookies, query string or client IP.
- exceptions: type, module and stack frames (file, function, line, our source lines). No
  exception message and no local variables.
- log events: the message template, never its arguments.
- no breadcrumbs, user, extra (sys.argv holds CLI arguments such as invite emails) or
  request-derived contexts.

Tracing is off unless SENTRY_TRACES_SAMPLE_RATE is set; transactions go through the same
allowlist, and spans keep only their operation, description and timing."""

from typing import Any

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from app.config import get_settings

_EVENT_KEYS = ("event_id", "timestamp", "start_timestamp", "type", "platform", "level", "logger",
               "transaction", "transaction_info", "release", "environment", "server_name", "sdk", "fingerprint")
_FRAME_KEYS = ("filename", "abs_path", "module", "function", "lineno", "colno", "in_app",
               "context_line", "pre_context", "post_context")
_CONTEXTS = ("runtime", "os", "trace")
_SPAN_KEYS = ("span_id", "parent_span_id", "trace_id", "op", "description", "status",
              "start_timestamp", "timestamp", "origin")
# Set on every event by init(); anything else in tags is dropped.
_TAGS = ("component",)

_initialized = False


def _pick(source: dict, keys: tuple[str, ...]) -> dict:
    return {k: source[k] for k in keys if k in source}


def _path_only(url: str) -> str:
    return url.split("?", 1)[0].split("#", 1)[0]


def _exception(value: dict) -> dict:
    out = _pick(value, ("type", "module"))
    if "mechanism" in value:
        out["mechanism"] = _pick(value["mechanism"], ("type", "handled", "synthetic", "exception_id", "parent_id"))
    frames = (value.get("stacktrace") or {}).get("frames") or []
    if frames:
        out["stacktrace"] = {"frames": [_pick(f, _FRAME_KEYS) for f in frames]}
    return out


def scrub(event: dict[str, Any], _hint: Any = None) -> dict[str, Any]:
    """before_send / before_send_transaction: the event rebuilt from the allowlist."""
    out = _pick(event, _EVENT_KEYS)
    request = event.get("request") or {}
    if request:
        out["request"] = {k: v for k, v in (("method", request.get("method")),
                                             ("url", _path_only(request.get("url") or ""))) if v}
    values = (event.get("exception") or {}).get("values") or []
    if values:
        out["exception"] = {"values": [_exception(v) for v in values]}
    logentry = event.get("logentry") or {}
    if logentry.get("message"):
        out["logentry"] = {"message": logentry["message"]}  # the template; params are dropped
    contexts = _pick(event.get("contexts") or {}, _CONTEXTS)
    if "trace" in contexts:
        contexts["trace"] = _pick(contexts["trace"], _SPAN_KEYS)
    if contexts:
        out["contexts"] = contexts
    tags = _pick(event.get("tags") or {}, _TAGS)
    if tags:
        out["tags"] = tags
    if event.get("spans"):
        out["spans"] = [_pick(s, _SPAN_KEYS) for s in event["spans"]]
    return out


def init(component: str, *, transport: Any = None) -> bool:
    """Start reporting for this process ("api" or "cron") if SENTRY_DSN is set. Idempotent.
    `transport` is for tests."""
    global _initialized
    s = get_settings()
    if _initialized or not s.sentry_dsn:
        return _initialized
    sentry_sdk.init(
        dsn=s.sentry_dsn,
        environment=s.sentry_environment,
        release=s.sentry_release or None,
        # Collect nothing user-supplied in the first place (scrub is the second line). gen_ai
        # off matters: the Anthropic integration would otherwise record prompts, i.e. resumes.
        data_collection={
            "user_info": False, "cookies": {"mode": "off"}, "http_headers": {"request": {"mode": "off"}},
            "http_bodies": [], "url_query_params": {"mode": "off"}, "gen_ai": {"inputs": False, "outputs": False},
            "database_query_data": False, "queues": False, "stack_frame_variables": False,
        },
        max_breadcrumbs=0,
        traces_sample_rate=s.sentry_traces_sample_rate,
        before_send=scrub,
        before_send_transaction=scrub,
        # Error-level logs become events (template only); lower levels aren't collected at all.
        integrations=[LoggingIntegration(level=None, event_level="ERROR")],
        transport=transport,
    )
    sentry_sdk.set_tag("component", component)
    _initialized = True
    return True


def reset() -> None:
    """Tests: stop reporting and allow init() again."""
    global _initialized
    sentry_sdk.init(dsn="")  # not None: None means "read SENTRY_DSN"
    _initialized = False
