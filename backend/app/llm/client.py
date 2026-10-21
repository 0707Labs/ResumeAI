"""Thin wrapper over the Anthropic SDK for structured (pydantic) outputs.

Everything that calls Claude goes through `LLM.parse`, so tests swap in a fake
and the rest of the app never touches SDK types.
"""

import logging
import os
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from app.config import get_settings

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Claude couldn't produce a usable answer; callers fall back to rules-only."""


class LLM(Protocol):
    def parse(self, *, system: str, user: str, schema: type[T], effort: str = "medium") -> T: ...


class ClaudeLLM:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL,
                 on_usage: Callable[[str, Any], None] | None = None):
        self.client = client or anthropic.Anthropic(default_headers=_workspace_header())
        self.model = model
        # Called with (schema name, response) after every response, for cost tracking.
        self.on_usage = on_usage
        # (schema name, input tokens, output tokens) per successful call, for cost checks.
        self.usage: list[tuple[str, int, int]] = []

    def parse(self, *, system: str, user: str, schema: type[T], effort: str = "medium") -> T:
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
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
            raise LLMError(_describe(exc)) from exc

        self.usage.append((schema.__name__, response.usage.input_tokens,
                           response.usage.output_tokens))
        if self.on_usage is not None:
            self.on_usage(schema.__name__, response)
        if response.stop_reason == "refusal":
            raise LLMError("Claude declined this request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("Claude's answer was cut off.")
        if response.parsed_output is None:
            raise LLMError("Claude returned output that didn't match the schema.")
        return response.parsed_output


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

    return ClaudeLLM(on_usage=record_llm_usage)
