from enum import StrEnum

from pydantic import Field, model_validator

from .base import StrictModel


class Priority(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"


class RequirementCategory(StrEnum):
    SKILL = "skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    OTHER = "other"


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"
    UNKNOWN = "unknown"


class Requirement(StrictModel):
    id: str = Field(pattern=r"^req[0-9]+$")
    text: str = Field(min_length=1)
    priority: Priority
    category: RequirementCategory = RequirementCategory.OTHER
    # Normalized terms the ATS scorer matches on, e.g. ["python", "fastapi"].
    keywords: list[str] = Field(default_factory=list)


class JobDescription(StrictModel):
    title: str | None = None
    company: str | None = None
    seniority: Seniority = Seniority.UNKNOWN
    years_experience_min: int | None = Field(default=None, ge=0)
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    raw_text: str = ""

    @model_validator(mode="after")
    def _ids_are_unique(self) -> "JobDescription":
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate requirement id")
        return self

    def keywords(self, priority: Priority) -> list[str]:
        out: list[str] = []
        for req in self.requirements:
            if req.priority == priority:
                out.extend(k for k in req.keywords if k not in out)
        return out
