from enum import StrEnum

from pydantic import Field, computed_field

from .base import StrictModel


class ChangeType(StrEnum):
    """Rule 2: the only kinds of edit the tailor may make."""

    UNCHANGED = "unchanged"
    REORDER = "reorder"
    REWORD = "reword"
    MIRROR_TERMINOLOGY = "mirror_terminology"
    SURFACE_METRIC = "surface_metric"


class FlagKind(StrEnum):
    MISSING_SOURCE = "missing_source"  # rule 4
    UNKNOWN_SOURCE = "unknown_source"  # cites a bullet id that isn't in the resume
    NEW_TOOL = "new_tool"
    NEW_NUMBER = "new_number"
    NEW_TITLE = "new_title"
    NEW_EMPLOYER = "new_employer"
    INFLATED_VERB = "inflated_verb"  # rule 3: "contributed" -> "led"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class VerificationFlag(StrictModel):
    kind: FlagKind
    token: str = ""  # the offending term, e.g. "Kubernetes" or "40%"
    detail: str


class VerificationResult(StrictModel):
    flags: list[VerificationFlag] = Field(default_factory=list)

    @computed_field
    @property
    def passed(self) -> bool:
        return not self.flags


class TailoredBullet(StrictModel):
    id: str = Field(pattern=r"^t[0-9]+$")
    text: str = Field(min_length=1)
    # Rule 4. Deliberately not min_length=1 here: an unsourced bullet must still
    # parse so the verifier can reject it with a MISSING_SOURCE flag the user sees.
    source_bullet_ids: list[str] = Field(default_factory=list)
    # Clarifying-question ids whose candidate answers back this bullet (rule 1).
    source_answer_ids: list[str] = Field(default_factory=list)
    change_type: ChangeType
    jd_terms_used: list[str] = Field(default_factory=list)
    verification: VerificationResult | None = None
    review: ReviewStatus = ReviewStatus.PENDING


class TailoredResume(StrictModel):
    entry_order: list[str] = Field(default_factory=list)  # entry ids, best match first
    bullets: list[TailoredBullet] = Field(default_factory=list)
    summary: str | None = None
