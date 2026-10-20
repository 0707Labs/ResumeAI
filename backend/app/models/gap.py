from enum import StrEnum

from pydantic import Field, model_validator

from .base import StrictModel


class GapStatus(StrEnum):
    EVIDENCED = "evidenced"  # a bullet states it directly
    IMPLIED = "implied"  # bullets suggest it, but don't name it
    MISSING = "missing"  # nothing in the resume supports it


class ClarifyingQuestion(StrictModel):
    """Rule 6: a missing requirement becomes a question, never an auto-filled claim."""

    id: str = Field(pattern=r"^q[0-9]+$")
    requirement_id: str
    question: str = Field(min_length=1)
    # Filled in only by the candidate. Tailoring may cite an answer only when set.
    answer: str | None = None


class GapItem(StrictModel):
    requirement_id: str
    requirement_text: str
    status: GapStatus
    evidence_bullet_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    question: ClarifyingQuestion | None = None

    @model_validator(mode="after")
    def _status_matches_evidence(self) -> "GapItem":
        if self.status == GapStatus.MISSING:
            if self.evidence_bullet_ids:
                raise ValueError("a missing requirement cannot cite evidence")
            if self.question is None:
                raise ValueError("a missing requirement needs a clarifying question")
        elif not self.evidence_bullet_ids:
            raise ValueError(f"{self.status} requires at least one evidence bullet id")
        if self.question and self.question.requirement_id != self.requirement_id:
            raise ValueError("question.requirement_id must match requirement_id")
        return self


class GapAnalysis(StrictModel):
    items: list[GapItem] = Field(default_factory=list)

    def questions(self) -> list[ClarifyingQuestion]:
        return [i.question for i in self.items if i.question]
