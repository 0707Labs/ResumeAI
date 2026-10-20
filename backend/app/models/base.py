from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class StrictModel(BaseModel):
    """Base for every schema: unknown fields are rejected, so LLM output that
    invents extra keys fails validation instead of slipping through."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_fields(cls, data: Any) -> Any:
        # Computed fields appear in model_dump() output; ignore them on input so
        # a dumped model round-trips (they're always recomputed, never trusted).
        if isinstance(data, dict) and cls.model_computed_fields:
            return {k: v for k, v in data.items() if k not in cls.model_computed_fields}
        return data
