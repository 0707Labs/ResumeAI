from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import StrictModel
from .gap import GapStatus
from .jd import Priority


class GapSeverity(StrEnum):
    CRITICAL = "critical"  # a required item with nothing behind it
    MODERATE = "moderate"  # required but only implied, or partly covered
    MINOR = "minor"  # preferred items, or covered by a confirmed answer


class ActionKind(StrEnum):
    ANSWER_QUESTION = "answer_question"
    RESUME_EDIT = "resume_edit"
    LEARN = "learn"
    APPLY_STRATEGY = "apply_strategy"


class Decision(StrEnum):
    STRONG_FIT = "strong_fit"  # apply now
    APPLY = "apply"  # apply, after the quick fixes
    STRETCH = "stretch"  # worth a shot with prep and a good story
    NOT_YET = "not_yet"  # build the missing pieces first


class Strength(StrictModel):
    text: str
    evidence_bullet_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


class MentorGap(StrictModel):
    requirement_id: str | None = None  # None for resume-level gaps (format, metrics)
    text: str
    priority: Priority | None = None
    status: GapStatus | None = None
    severity: GapSeverity
    why_it_matters: str


class Action(StrictModel):
    id: str = Field(pattern=r"^a[0-9]+$")
    kind: ActionKind
    text: str
    effort: str  # "5 min", "1 hour", ...
    requirement_ids: list[str] = Field(default_factory=list)
    bullet_ids: list[str] = Field(default_factory=list)
    question_id: str | None = None


class Verdict(StrictModel):
    decision: Decision
    headline: str
    reasons: list[str]
    caveat: str = ("This is guidance from what the resume and JD say, not a prediction. "
                   "Hiring teams weigh things this can't see.")


class PlanTask(StrictModel):
    id: str = Field(pattern=r"^w[12]t[0-9]+$")
    days: str  # "Days 1-2"
    title: str
    detail: str
    deliverable: str
    requirement_ids: list[str] = Field(default_factory=list)


class PlanWeek(StrictModel):
    week: int = Field(ge=1, le=2)
    focus: str
    tasks: list[PlanTask]


class UpskillingPlan(StrictModel):
    focus_skills: list[str]
    hours_per_day: str = "1-2 hours"
    weeks: list[PlanWeek]
    not_addressable: list[str] = Field(default_factory=list)  # e.g. years, degree


class TalkingPoint(StrictModel):
    """Something to prepare for the interview, grounded in the resume or an answer."""

    id: str = Field(pattern=r"^tp[0-9]+$")
    kind: Literal["strength", "answer", "gap"]
    prompt: str
    detail: str
    bullet_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


class MentorAdvice(StrictModel):
    strengths: list[Strength]
    gaps: list[MentorGap]
    actions: list[Action]
    verdict: Verdict
    plan: UpskillingPlan
    talking_points: list[TalkingPoint] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
