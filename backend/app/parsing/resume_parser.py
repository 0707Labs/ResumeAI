"""Structure extracted lines into a Resume with stable bullet IDs.

Deterministic heuristics, no LLM: the IDs produced here are the anchors the
anti-fabrication verifier checks against, so the same file must always parse
the same way.
"""

import re
from dataclasses import dataclass, field

from app.models import (
    Bullet,
    ContactInfo,
    Entry,
    ParseWarning,
    ParseWarningCode,
    Resume,
    Section,
    SectionKind,
)

from .extract import Extracted, extract, lines_from_text
from .lexicon import DEGREE_WORDS, INSTITUTION_WORDS, ORG_SUFFIX, TITLE_WORDS
from .text import (
    DATE_RANGE_RE,
    EMAIL_RE,
    PHONE_RE,
    SINGLE_DATE_RE,
    URL_RE,
    Line,
    has_date,
    is_contact_line,
    join_wrapped,
    normalize_space,
    strip_bullet,
)

# Pseudo-kinds for sections that don't hold entries.
SUMMARY, SKILLS = "summary", "skills"

_HEADINGS: dict[str, SectionKind | str] = {}
for _kind, _names in {
    SectionKind.EXPERIENCE: [
        "experience", "work experience", "professional experience", "employment",
        "employment history", "work history", "career history", "relevant experience",
        "internships", "internship experience", "internship", "experience and internships",
    ],
    SectionKind.PROJECTS: [
        "projects", "personal projects", "academic projects", "key projects",
        "selected projects", "project experience", "side projects",
    ],
    SectionKind.EDUCATION: ["education", "academic background", "education and training",
                            "academics", "academic qualifications", "educational qualifications"],
    SectionKind.CERTIFICATIONS: [
        "certifications", "certificates", "certification", "licenses and certifications",
        "courses", "certifications and courses", "courses and certifications", "training",
    ],
    SUMMARY: ["summary", "professional summary", "profile", "about me", "objective",
              "career objective", "about", "professional profile", "career summary"],
    SKILLS: ["skills", "technical skills", "core skills", "key skills", "skills and tools",
             "tools", "technologies", "core competencies", "competencies", "tech stack",
             "tools and technologies", "skills and technologies", "technical proficiencies"],
    SectionKind.OTHER: [
        "awards", "achievements", "honors", "honors and awards", "awards and achievements",
        "publications", "volunteering", "volunteer experience", "leadership", "activities",
        "extracurricular activities", "extracurriculars", "interests", "languages", "hobbies",
        "positions of responsibility",
    ],
}.items():
    for _n in _names:
        _HEADINGS[_n] = _kind

_HEADING_STEMS: list[tuple[str, SectionKind | str]] = [
    ("experience", SectionKind.EXPERIENCE), ("employment", SectionKind.EXPERIENCE),
    ("project", SectionKind.PROJECTS), ("education", SectionKind.EDUCATION),
    ("certif", SectionKind.CERTIFICATIONS), ("skill", SKILLS), ("summary", SUMMARY),
    ("profile", SUMMARY), ("objective", SUMMARY), ("award", SectionKind.OTHER),
    ("achievement", SectionKind.OTHER), ("publication", SectionKind.OTHER),
    ("volunteer", SectionKind.OTHER), ("activit", SectionKind.OTHER),
]

_ID_PREFIX = {
    SectionKind.EXPERIENCE: "exp", SectionKind.PROJECTS: "proj",
    SectionKind.EDUCATION: "edu", SectionKind.CERTIFICATIONS: "cert",
    SectionKind.OTHER: "oth",
}

_STRONG_SEP = re.compile(r"\s+[|•·]\s+|\s+[–—]\s+|\s+-\s+")
_LOCATION = re.compile(r"^(remote|hybrid|on-?site|[A-Z][\w .'-]+,\s*[A-Z][\w .'-]+)$")
_VERB_START = re.compile(r"^[A-Z][a-z]+(ed|ing)\b")


def parse_resume_file(data: bytes, filename: str) -> Resume:
    return _build(extract(data, filename))


def parse_resume_text(text: str) -> Resume:
    return _build(Extracted(lines_from_text(text)))


# --- line classification -----------------------------------------------------------


def _heading_kind(line: Line) -> tuple[SectionKind | str, str] | None:
    """(kind, inline content after a colon) if the line is a section heading."""
    text = line.text
    inline = ""
    m = re.match(r"^([A-Za-z &/]+):\s*(.*)$", text)
    if m and len(m.group(1).split()) <= 5:
        text, inline = m.group(1), m.group(2)
    key = re.sub(r"\s+", " ", text.lower().replace("&", "and")).strip(" :")
    if key in _HEADINGS:
        return _HEADINGS[key], inline
    words = key.split()
    looks_like_heading = (
        len(words) <= 5
        and not has_date(text)
        and (text.isupper() or line.text.endswith(":"))
    )
    if looks_like_heading:
        for stem, kind in _HEADING_STEMS:
            if stem in key:
                return kind, inline
    return None


def _has_title_word(text: str) -> bool:
    words = re.findall(r"[a-z][a-z\-]*", text.lower())
    return any(w in TITLE_WORDS for w in words) or bool(DEGREE_WORDS.search(text))


def _is_header_like(line: Line) -> bool:
    """Job/project/degree header rather than bullet prose."""
    text = line.text
    if DATE_RANGE_RE.search(text) or SINGLE_DATE_RE.search(text.split()[-1] if text else ""):
        return True
    if len(line.segments) > 1 or " | " in text:
        return True
    if text.endswith((".", ";")) or _VERB_START.match(text):
        return False
    short = len(text.split()) <= 8
    org_like = bool(ORG_SUFFIX.search(text) or INSTITUTION_WORDS.search(text))
    return short and (_has_title_word(text) or org_like or text.istitle())


def _looks_like_name(text: str) -> bool:
    words = text.split()
    return (
        1 <= len(words) <= 4
        and all(re.fullmatch(r"[A-Za-z][A-Za-z.'\-]*", w) for w in words)
        and not _has_title_word(text)
    )


# --- header parsing -----------------------------------------------------------------


def _parse_header(lines: list[Line], kind: SectionKind) -> dict:
    start = end = location = None
    pieces: list[str] = []
    for line in lines:
        for seg in line.segments:
            m = DATE_RANGE_RE.search(seg)
            if m and start is None:
                start, end = m.group("start"), m.group("end")
                seg = (seg[: m.start()] + seg[m.end():]).strip(" ,|()–—-")
            elif start is None and (sm := SINGLE_DATE_RE.search(seg)) and (
                len(seg.split()) <= 3 or sm.end() == len(seg.rstrip(" )"))
            ):
                end = sm.group(0)
                seg = (seg[: sm.start()] + seg[sm.end():]).strip(" ,|()–—-")
            if seg:
                pieces.extend(p.strip(" ,") for p in _split_header(seg) if p.strip(" ,"))
    title = org = None
    rest: list[str] = []
    for p in pieces:
        if location is None and _LOCATION.match(p) and not ORG_SUFFIX.search(p) \
                and not _has_title_word(p) and not INSTITUTION_WORDS.search(p):
            location = p
        elif title is None and _is_title_piece(p, kind):
            title = p
        else:
            rest.append(p)
    if rest:
        org = rest.pop(0)
    if title is None and rest:
        title = rest.pop(0)
    if kind == SectionKind.PROJECTS and title is None and org is not None:
        title, org = org, None  # a project header is usually just its name
    return {"title": title, "organization": org, "location": location,
            "start_date": start, "end_date": end}


def _split_header(seg: str) -> list[str]:
    parts = _STRONG_SEP.split(seg)
    if len(parts) == 1:
        m = re.match(r"^(.+?)\s+at\s+(.+)$", seg)
        if m and _has_title_word(m.group(1)):
            return [m.group(1), m.group(2)]
        # "Data Analyst, Acme Corp" but not "Acme, Inc." or "Bengaluru, India"
        if "," in seg:
            first, second = seg.split(",", 1)
            if _has_title_word(first) and not ORG_SUFFIX.match(second.strip()):
                return [first, second]
    return parts


def _is_title_piece(p: str, kind: SectionKind) -> bool:
    if kind == SectionKind.EDUCATION:
        return bool(DEGREE_WORDS.search(p)) and not INSTITUTION_WORDS.search(p)
    return _has_title_word(p) and not INSTITUTION_WORDS.search(p)


# --- builder ------------------------------------------------------------------------


@dataclass
class _EntryDraft:
    kind: SectionKind
    header: list[Line] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    last_bullet_x0: float | None = None


@dataclass
class _SectionDraft:
    kind: SectionKind
    heading: str
    entries: list[_EntryDraft] = field(default_factory=list)


def _build(ex: Extracted) -> Resume:
    lines = ex.lines
    warnings = list(ex.warnings)
    doc_has_glyphs = any(strip_bullet(l.text)[0] or l.is_list_item for l in lines)

    name: str | None = None
    contact = ContactInfo()
    summary: list[str] = []
    skills: list[str] = []
    sections: list[_SectionDraft] = []
    current: SectionKind | str | None = None  # None = preamble above first heading
    found_heading = False

    for line in lines:
        _collect_contact(line.text, contact)
        heading = _heading_kind(line)
        if heading and heading[1] and current == SKILLS:
            heading = None  # "Languages: Python, SQL" is a skills category, not a section
        if heading:
            found_heading = True
            current, inline = heading
            if isinstance(current, SectionKind):
                sections.append(_SectionDraft(current, line.text.split(":")[0].strip()))
            if inline:
                _add_to_simple(current, inline, summary, skills)
            continue

        if current is None:
            if name is None and _looks_like_name(line.text) and not is_contact_line(line.text):
                name = line.text.title() if line.text.isupper() else line.text
            elif not is_contact_line(line.text):
                summary.append(line.text)
            continue
        if current in (SUMMARY, SKILLS):
            _add_to_simple(current, line.text, summary, skills)
            continue
        _add_entry_line(sections[-1], line, doc_has_glyphs)

    resume_sections = _finalize(sections)
    raw_text = "\n".join(l.text for l in lines)

    if not found_heading:
        warnings.append(ParseWarning(code=ParseWarningCode.NO_SECTIONS_FOUND,
                                     message="No standard section headings (Experience, "
                                             "Education, Skills) found."))
    if not any(e.bullets for s in resume_sections for e in s.entries):
        warnings.append(ParseWarning(code=ParseWarningCode.NO_BULLETS_FOUND,
                                     message="No bullet points found under any section."))
    if not contact.email:
        warnings.append(ParseWarning(code=ParseWarningCode.CONTACT_MISSING,
                                     message="No email address found."))
    if not name:
        warnings.append(ParseWarning(code=ParseWarningCode.NAME_NOT_FOUND,
                                     message="Couldn't find your name at the top."))

    return Resume(
        name=name,
        contact=contact,
        summary=" ".join(summary) or None,
        skills=skills,
        sections=resume_sections,
        raw_text=raw_text,
        parse_warnings=warnings,
    )


def _collect_contact(text: str, contact: ContactInfo) -> None:
    if contact.email is None and (m := EMAIL_RE.search(text)):
        contact.email = m.group(0)
    if contact.phone is None and is_contact_line(text) and (m := PHONE_RE.search(text)):
        contact.phone = normalize_space(m.group(0))
    if contact.location is None and is_contact_line(text):
        for part in re.split(r"\s*[|•·]\s*", text):
            if _LOCATION.match(part.strip()) and not EMAIL_RE.search(part):
                contact.location = part.strip()
                break
    for m in URL_RE.finditer(EMAIL_RE.sub(" ", text)):
        link = m.group(0).rstrip("/.")
        if link not in contact.links:
            contact.links.append(link)


def _add_to_simple(kind, text: str, summary: list[str], skills: list[str]) -> None:
    if kind == SUMMARY:
        summary.append(strip_bullet(text)[1])
    elif kind == SKILLS:
        _, text = strip_bullet(text)
        if ":" in text:  # "Languages: Python, SQL"
            text = text.split(":", 1)[1]
        for item in re.split(r"[,;|•·]|\s{2,}|\s/\s", text):
            item = item.strip(" .")
            if item and item not in skills:
                skills.append(item)


def _add_entry_line(section: _SectionDraft, line: Line, doc_has_glyphs: bool) -> None:
    is_glyph, text = strip_bullet(line.text)
    is_bullet = is_glyph or line.is_list_item
    entry = section.entries[-1] if section.entries else None

    # Certifications, awards, etc.: every line is an item of one entry.
    if section.kind in (SectionKind.CERTIFICATIONS, SectionKind.OTHER):
        if entry is None:
            entry = _EntryDraft(section.kind)
            section.entries.append(entry)
        if entry.bullets and not is_bullet and _is_continuation(line, entry, doc_has_glyphs):
            entry.bullets[-1] = join_wrapped(entry.bullets[-1], text)
        else:
            entry.bullets.append(text)
            entry.last_bullet_x0 = line.x0
        return

    if is_bullet:
        if entry is None:
            entry = _EntryDraft(section.kind)
            section.entries.append(entry)
        entry.bullets.append(text)
        entry.last_bullet_x0 = line.x0
        return

    if entry and entry.bullets and _is_continuation(line, entry, doc_has_glyphs):
        entry.bullets[-1] = join_wrapped(entry.bullets[-1], line.text)
        return

    if entry and not entry.bullets and len(entry.header) < 3 and _is_header_like(line):
        entry.header.append(line)  # second line of a two-line header
        return

    if _is_header_like(line) or entry is None:
        section.entries.append(_EntryDraft(section.kind, header=[line]))
        return

    # No glyphs anywhere in the doc: prose lines under a header are the bullets.
    entry.bullets.append(line.text)
    entry.last_bullet_x0 = line.x0


def _is_continuation(line: Line, entry: _EntryDraft, doc_has_glyphs: bool) -> bool:
    text = line.text
    if text[:1].islower() or text[:1] in "(&" or text.startswith("and "):
        return True
    if _is_header_like(line):
        return False
    if line.x0 is not None and entry.last_bullet_x0 is not None \
            and line.x0 > entry.last_bullet_x0 + 3:
        return True  # indented under the bullet glyph
    if doc_has_glyphs:
        return True  # glyph docs: an unmarked non-header line is a wrapped bullet
    return not entry.bullets[-1].rstrip().endswith((".", "!", "?", ";"))


def _finalize(drafts: list[_SectionDraft]) -> list[Section]:
    counters: dict[str, int] = {}
    sections: list[Section] = []
    for draft in drafts:
        entries: list[Entry] = []
        for ed in draft.entries:
            prefix = _ID_PREFIX[ed.kind]
            counters[prefix] = counters.get(prefix, 0) + 1
            entry_id = f"{prefix}{counters[prefix]}"
            header = _parse_header(ed.header, ed.kind) if ed.header else {}
            bullets = [
                Bullet(id=f"{entry_id}.b{i}", text=normalize_space(t))
                for i, t in enumerate(ed.bullets, start=1)
                if t.strip()
            ]
            entries.append(Entry(id=entry_id, bullets=bullets, **header))
        sections.append(Section(kind=draft.kind, heading=draft.heading, entries=entries))
    return sections
