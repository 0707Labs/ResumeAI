from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.llm.client import MODEL, ClaudeLLM, LLMError


class Out(BaseModel):
    answer: str


class StubClient:
    """Stands in for anthropic.Anthropic; records the request it was given."""

    def __init__(self, response):
        self.kwargs = None
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))
        self._response = response

    def _parse(self, **kwargs):
        self.kwargs = kwargs
        return self._response


def resp(stop_reason="end_turn", parsed=Out(answer="ok")):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def test_request_shape():
    stub = StubClient(resp())
    out = ClaudeLLM(client=stub).parse(system="sys", user="hi", schema=Out, effort="low")
    assert out == Out(answer="ok")
    k = stub.kwargs
    assert k["model"] == MODEL == "claude-opus-5-5"
    assert k["output_format"] is Out
    assert k["output_config"] == {"effort": "low"}
    assert k["fallbacks"] == "default"
    assert k["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in k  # Opus 5.5 always thinks; effort is the control


@pytest.mark.parametrize("stop, parsed, msg", [
    ("refusal", None, "declined"),
    ("max_tokens", None, "cut off"),
    ("end_turn", None, "didn't match"),
])
def test_unusable_responses_raise(stop, parsed, msg):
    with pytest.raises(LLMError, match=msg):
        ClaudeLLM(client=StubClient(resp(stop, parsed))).parse(
            system="s", user="u", schema=Out)
