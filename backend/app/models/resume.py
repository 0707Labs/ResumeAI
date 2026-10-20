from enum import StrEnum

from pydantic import Field, model_validator

from .base import StrictModel

# Bullet IDs are stable handles that every tailored bullet must point back to.
# Format: "<entry_id>.b<n>", e.g. "exp1.b2"; entry IDs look like "exp1", "proj3".
ID_PATTERN = r"^[a-z]+[0-9]+(\.b[0-9]+)?$"


class SectionKind(StrEnum):
    EXPERIENCE = "experience"
    PROJECTS = "projects"
    EDUCATION = "education"
    CERTIFICATIONS = "certifications"
    OTHER = "other"


class Bullet(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    text: str = Field(min_length=1)


class Entry(StrictModel):
    """One job, project, or degree, with the bullets underneath it."""

    id: str = Field(pattern=ID_PATTERN)
    title: str | None = None
    organization: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    bullets: list[Bullet] = Field(default_factory=list)


class Section(StrictModel):
    kind: SectionKind
    heading: str
    entries: list[Entry] = Field(default_factory=list)


class ParseWarningCode(StrEnum):
    TABLES_DETECTED = "tables_detected"
    IMAGES_DETECTED = "images_detected"
    MULTI_COLUMN_SUSPECTED = "multi_column_suspected"
    NO_SECTIONS_FOUND = "no_sections_found"
    NO_BULLETS_FOUND = "no_bullets_found"
    CONTACT_MISSING = "contact_missing"
    NAME_NOT_FOUND = "name_not_found"


class ParseWarning(StrictModel):
    """Format problems found while parsing; feeds the ATS parseability score."""

    code: ParseWarningCode
    message: str


class ContactInfo(StrictModel):
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)


class Resume(StrictModel):
    name: str | None = None
    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    raw_text: str = ""
    parse_warnings: list[ParseWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> "Resume":
        seen: set[str] = set()
        for section in self.sections:
            for entry in section.entries:
                for id_ in [entry.id, *(b.id for b in entry.bullets)]:
                    if id_ in seen:
                        raise ValueError(f"duplicate id {id_!r}")
                    seen.add(id_)
        return self

    def entries(self) -> list[Entry]:
        return [e for s in self.sections for e in s.entries]

    def bullets(self) -> list[Bullet]:
        return [b for e in self.entries() for b in e.bullets]

    def bullet_by_id(self, bullet_id: str) -> Bullet | None:
        return next((b for b in self.bullets() if b.id == bullet_id), None)

    def entry_for_bullet(self, bullet_id: str) -> Entry | None:
        return next(
            (e for e in self.entries() if any(b.id == bullet_id for b in e.bullets)),
            None,
        )
