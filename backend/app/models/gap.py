import re
from enum import StrEnum

from pydantic import Field, computed_field, model_validator

from .base import StrictModel
from .jd import Priority, RequirementCategory


class GapStatus(StrEnum):
    EVIDENCED = "evidenced"  # the resume states it directly
    IMPLIED = "implied"  # related evidence suggests it, but doesn't name it
    MISSING = "missing"  # nothing in the resume supports it


class AnswerKind(StrEnum):
    UNANSWERED = "unanswered"
    CONFIRMED = "confirmed"  # candidate says yes and gives detail
    DECLINED = "declined"  # candidate says they don't have it


_NEGATIVE = re.compile(
    r"^\s*(no|nope|not really|never|n/a|none|i (have not|haven't|don't|do not)|haven't|don't)\b",
    re.IGNORECASE,
)


class ClarifyingQuestion(StrictModel):
    """Rule 6: a missing requirement becomes a question, never an auto-filled claim."""

    id: str = Field(pattern=r"^q[0-9]+$")
    requirement_id: str
    question: str = Field(min_length=1)
    # Filled in only by the candidate. Tailoring may cite an answer only when confirmed.
    answer: str | None = Field(default=None, max_length=2000)

    @computed_field
    @property
    def answer_kind(self) -> AnswerKind:
        if not self.answer or not self.answer.strip():
            return AnswerKind.UNANSWERED
        return AnswerKind.DECLINED if _NEGATIVE.match(self.answer) else AnswerKind.CONFIRMED


class GapItem(StrictModel):
    requirement_id: str
    requirement_text: str
    priority: Priority = Priority.REQUIRED
    category: RequirementCategory = RequirementCategory.OTHER
    status: GapStatus
    # Evidence can be bullets, whole entries (a degree with no bullets), or the
    # candidate's own Skills list. At least one is required unless MISSING.
    evidence_bullet_ids: list[str] = Field(default_factory=list)
    evidence_entry_ids: list[str] = Field(default_factory=list)
    evidence_skills: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    rationale: str = ""
    question: ClarifyingQuestion | None = None
    decided_by: str = "rules"  # "rules" or "llm"

    @model_validator(mode="after")
    def _status_matches_evidence(self) -> "GapItem":
        has_evidence = bool(
            self.evidence_bullet_ids or self.evidence_entry_ids or self.evidence_skills
        )
        if self.status == GapStatus.MISSING:
            if has_evidence:
                raise ValueError("a missing requirement cannot cite evidence")
            if self.question is None:
                raise ValueError("a missing requirement needs a clarifying question")
        elif not has_evidence:
            raise ValueError(f"{self.status} requires at least one piece of evidence")
        if self.question and self.question.requirement_id != self.requirement_id:
            raise ValueError("question.requirement_id must match requirement_id")
        return self


class GapAnalysis(StrictModel):
    items: list[GapItem] = Field(default_factory=list)
    candidate_years_experience: float | None = None
    notes: list[str] = Field(default_factory=list)  # e.g. whether Claude was used

    def questions(self) -> list[ClarifyingQuestion]:
        return [i.question for i in self.items if i.question]

    def confirmed_answers(self) -> dict[str, str]:
        """Question id -> answer text the tailor may cite via source_answer_ids."""
        return {
            q.id: q.answer for q in self.questions()
            if q.answer_kind == AnswerKind.CONFIRMED and q.answer
        }

    @computed_field
    @property
    def counts(self) -> dict[str, int]:
        return {s.value: sum(1 for i in self.items if i.status == s) for s in GapStatus}

    @computed_field
    @property
    def required_coverage(self) -> float:
        """Share of required items that are evidenced (1.0) or implied (0.5)."""
        req = [i for i in self.items if i.priority == Priority.REQUIRED]
        if not req:
            return 1.0
        credit = {GapStatus.EVIDENCED: 1.0, GapStatus.IMPLIED: 0.5, GapStatus.MISSING: 0.0}
        return round(sum(credit[i.status] for i in req) / len(req), 3)
