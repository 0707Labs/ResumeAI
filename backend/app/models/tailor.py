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
    UNKNOWN_SOURCE = "unknown_source"  # cites a bullet/answer that doesn't exist or isn't confirmed
    CROSS_ENTRY = "cross_entry"  # merges bullets from different jobs into one
    NEW_TOOL = "new_tool"
    NEW_NUMBER = "new_number"
    NEW_TITLE = "new_title"
    NEW_EMPLOYER = "new_employer"
    INFLATED_VERB = "inflated_verb"  # rule 3: "contributed" -> "led"
    NEW_CLAIM = "new_claim"  # wording not traceable to the source; needs a human look


class Severity(StrEnum):
    BLOCK = "block"  # the bullet is rejected
    WARN = "warn"  # shown to the user for review; doesn't reject


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class VerificationFlag(StrictModel):
    kind: FlagKind
    token: str = ""  # the offending term, e.g. "Kubernetes" or "40%"
    detail: str
    severity: Severity = Severity.BLOCK


class VerificationResult(StrictModel):
    flags: list[VerificationFlag] = Field(default_factory=list)

    @computed_field
    @property
    def passed(self) -> bool:
        return not any(f.severity == Severity.BLOCK for f in self.flags)


class RejectedAttempt(StrictModel):
    """A rewrite the verifier blocked, kept so the user can see what was refused."""

    text: str
    flags: list[VerificationFlag]


class TailoredBullet(StrictModel):
    id: str = Field(pattern=r"^t[0-9]+$")
    text: str = Field(min_length=1)
    # Rule 4. Deliberately not min_length=1 here: an unsourced bullet must still
    # parse so the verifier can reject it with a MISSING_SOURCE flag the user sees.
    source_bullet_ids: list[str] = Field(default_factory=list)
    # Clarifying-question ids whose confirmed candidate answers back this bullet (rule 1).
    source_answer_ids: list[str] = Field(default_factory=list)
    entry_id: str | None = None
    original_text: str = ""  # source bullet text(s), for the diff view
    change_type: ChangeType
    jd_terms_used: list[str] = Field(default_factory=list)
    verification: VerificationResult | None = None
    rejected_attempts: list[RejectedAttempt] = Field(default_factory=list)
    review: ReviewStatus = ReviewStatus.PENDING


class TailoredResume(StrictModel):
    entry_order: list[str] = Field(default_factory=list)  # entry ids, display order
    bullets: list[TailoredBullet] = Field(default_factory=list)
    summary: str | None = None
    summary_verification: VerificationResult | None = None
    notes: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def blocked_rewrites(self) -> int:
        return sum(len(b.rejected_attempts) for b in self.bullets)
