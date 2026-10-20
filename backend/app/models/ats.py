import math
from enum import StrEnum

from pydantic import Field, computed_field, model_validator

from .base import StrictModel


class Component(StrEnum):
    REQUIRED_KEYWORDS = "required_keywords"
    PREFERRED_KEYWORDS = "preferred_keywords"
    SEMANTIC_RELEVANCE = "semantic_relevance"
    TITLE_SENIORITY = "title_seniority"
    FORMAT_PARSEABILITY = "format_parseability"
    QUANTIFIED_IMPACT = "quantified_impact"


WEIGHTS: dict[Component, float] = {
    Component.REQUIRED_KEYWORDS: 0.40,
    Component.PREFERRED_KEYWORDS: 0.10,
    Component.SEMANTIC_RELEVANCE: 0.20,
    Component.TITLE_SENIORITY: 0.10,
    Component.FORMAT_PARSEABILITY: 0.10,
    Component.QUANTIFIED_IMPACT: 0.10,
}

DISCLAIMER = (
    "This is an estimate. Real ATS systems (Workday, Greenhouse, Lever, Taleo, ...) "
    "parse and rank differently, and many rely on recruiter filters, not a single score."
)


class ScoreComponent(StrictModel):
    name: Component
    score: float = Field(ge=0.0, le=1.0)  # 0..1 before weighting
    deterministic: bool = True  # False for the LLM-judged semantic component
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    notes: str = ""

    @computed_field
    @property
    def weight(self) -> float:
        return WEIGHTS[self.name]

    @computed_field
    @property
    def points(self) -> float:
        return round(self.score * self.weight * 100, 1)


class ATSReport(StrictModel):
    components: list[ScoreComponent]
    disclaimer: str = DISCLAIMER

    @model_validator(mode="after")
    def _all_components_once(self) -> "ATSReport":
        names = [c.name for c in self.components]
        if sorted(names) != sorted(WEIGHTS):
            raise ValueError("ATSReport needs exactly one score per component")
        return self

    @computed_field
    @property
    def total(self) -> float:
        """0..100 weighted score."""
        return round(math.fsum(c.score * c.weight for c in self.components) * 100, 1)


assert math.isclose(sum(WEIGHTS.values()), 1.0)
