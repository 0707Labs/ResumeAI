"""Thin wrapper over the Anthropic SDK for structured (pydantic) outputs.

Everything that calls Claude goes through `LLM.parse`, so tests swap in a fake
and the rest of the app never touches SDK types.
"""

import logging
import os
import time
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from app.config import get_settings

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Claude couldn't produce a usable answer; callers fall back to rules-only."""


class LLM(Protocol):
    def parse(self, *, system: str, user: str, schema: type[T], effort: str = "medium") -> T: ...


class ClaudeLLM:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL,
                 on_usage: Callable[[str, Any], None] | None = None,
                 step_models: Callable[[str], Any] | None = None):
        self.client = client or anthropic.Anthropic(default_headers=_workspace_header())
        self.model = model
        # Pipeline step -> configured model/max_tokens/effort, or None for the defaults
        # here (app.llm.models.for_step in the app).
        self.step_models = step_models
        # Called after every call for cost tracking: (schema name, response or None) plus
        # latency_ms, status (ok, refused, truncated, invalid, error, rate_limited) and error_code.
        self.on_usage = on_usage
        # (schema name, input tokens, output tokens) per successful call, for cost checks.
        self.usage: list[tuple[str, int, int]] = []

    def parse(self, *, system: str, user: str, schema: type[T], effort: str = "medium") -> T:
        model, max_tokens = self.model, MAX_TOKENS
        if self.step_models is not None:
            from app.billing.costs import pipeline_step

            if (chosen := self.step_models(pipeline_step(schema.__name__))) is not None:
                model, max_tokens, effort = chosen.model, chosen.max_tokens, chosen.effort
        started = time.monotonic()
        try:
            response = self.client.beta.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": effort},
                # If a safety classifier declines, re-run on Anthropic's recommended
                # fallback model instead of failing the request.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIError as exc:
            log.warning("Claude call for %s failed: %s", schema.__name__, exc)
            self._report(schema.__name__, None, started, "rate_limited" if isinstance(exc, anthropic.RateLimitError)
                         else "error", _error_code(exc))
            raise LLMError(_describe(exc)) from exc

        self.usage.append((schema.__name__, response.usage.input_tokens,
                           response.usage.output_tokens))
        status = ("refused" if response.stop_reason == "refusal" else "truncated" if response.stop_reason == "max_tokens"
                  else "invalid" if response.parsed_output is None else "ok")
        self._report(schema.__name__, response, started, status, None)
        if response.stop_reason == "refusal":
            raise LLMError("Claude declined this request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("Claude's answer was cut off.")
        if response.parsed_output is None:
            raise LLMError("Claude returned output that didn't match the schema.")
        return response.parsed_output


    def _report(self, stage: str, response: Any, started: float, status: str, error_code: str | None) -> None:
        if self.on_usage is not None:
            self.on_usage(stage, response, latency_ms=round((time.monotonic() - started) * 1000), status=status,
                          error_code=error_code)


def _error_code(exc: anthropic.APIError) -> str:
    """A short, content-free code for the cost views ("api_429", "connection")."""
    if isinstance(exc, anthropic.APIStatusError):
        return f"api_{exc.status_code}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "connection"
    return type(exc).__name__[:80]


def _workspace_header() -> dict[str, str]:
    """Org-level (unscoped) API keys must name a workspace on every request."""
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    return {"anthropic-workspace-id": workspace} if workspace else {}


def _describe(exc: anthropic.APIError) -> str:
    if isinstance(exc, anthropic.RateLimitError):
        return "Claude rate limit hit; try again shortly."
    if isinstance(exc, anthropic.APIStatusError):
        return f"Claude API error ({exc.status_code})."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Couldn't reach the Claude API."
    return "Claude API error."


def get_llm() -> LLM | None:
    """None when no API key is configured: features degrade to rules-only."""
    if not get_settings().llm_configured:
        return None
    from app.billing.costs import record_llm_usage

    from app.llm.models import for_step

    return ClaudeLLM(on_usage=record_llm_usage, step_models=for_step)
