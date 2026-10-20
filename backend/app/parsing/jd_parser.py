"""Parse pasted job-description text into a JobDescription. Deterministic."""

import re

from app.models import JobDescription, Priority, Requirement, RequirementCategory, Seniority

from .lexicon import DEGREE_WORDS, TITLE_WORDS, find_skills
from .text import strip_bullet

_RESP, _REQ, _PREF, _ABOUT, _SKIP = "resp", "req", "pref", "about", "skip"

_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Order matters: "preferred qualifications" must win over "qualifications".
    (_PREF, re.compile(r"\b(preferred|nice[\s-]to[\s-]haves?|bonus|pluses|good[\s-]to[\s-]have|"
                       r"desired|extra credit|would be great)\b", re.I)),
    (_REQ, re.compile(r"\b(requirements?|qualifications?|must[\s-]haves?|what you('ll| will)? "
                      r"(need|bring)|who you are|what we('re| are) looking for|you have|"
                      r"skills( and experience)?|about you|required)\b", re.I)),
    (_RESP, re.compile(r"\b(responsibilities|what you('ll| will) do|the role|duties|"
                       r"your impact|day[\s-]to[\s-]day|what you('ll| will) work on|key tasks)\b",
                       re.I)),
    (_ABOUT, re.compile(r"^about\b", re.I)),
    (_SKIP, re.compile(r"\b(benefits|perks|what we offer|compensation|salary|equal opportunity|"
                       r"how to apply|why join)\b", re.I)),
]

_PLUS_WORDS = re.compile(r"\b(a plus|is a plus|are a plus|plus\b|preferred|nice to have|bonus|"
                         r"ideally|desirable|advantageous|good to have|would (help|be (nice|great|helpful)))", re.I)
_MUST_WORDS = re.compile(r"\b(must|required|mandatory|minimum|at least)\b", re.I)
_YEARS_RE = re.compile(
    r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s*\+?\s*"
    r"(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)", re.I)
_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten".split())}
_LABEL_RE = re.compile(r"^(job title|title|position|role|company|organization)\s*:\s*(.+)$", re.I)

_SENIORITY_WORDS: list[tuple[re.Pattern[str], Seniority]] = [
    (re.compile(r"\bintern(ship)?\b", re.I), Seniority.INTERN),
    (re.compile(r"\b(principal|distinguished|director|head of|vp)\b", re.I), Seniority.PRINCIPAL),
    (re.compile(r"\b(lead|staff)\b", re.I), Seniority.LEAD),
    (re.compile(r"\b(senior|sr\.?|iii)\b", re.I), Seniority.SENIOR),
    (re.compile(r"\b(junior|jr\.?|entry[\s-]level|graduate|associate|i)\b", re.I), Seniority.JUNIOR),
    (re.compile(r"\b(mid[\s-]level|ii)\b", re.I), Seniority.MID),
]


def parse_jd(text: str) -> JobDescription:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title, company = _title_and_company(lines)

    section: str | None = None
    responsibilities: list[str] = []
    req_lines: list[tuple[str, Priority]] = []
    loose: list[str] = []  # lines outside any recognised section
    for line in lines:
        kind = _section_heading(line)
        if kind:
            section = kind
            if kind == _ABOUT and company is None:
                company = _company_from_about(line)
            inline = line.split(":", 1)[1].strip() if ":" in line else ""
            if not inline:
                continue
            line = inline
        _, item = strip_bullet(line)
        if section == _RESP:
            responsibilities.append(item)
        elif section == _REQ:
            req_lines.append((item, Priority.REQUIRED))
        elif section == _PREF:
            req_lines.append((item, Priority.PREFERRED))
        elif section is None:
            loose.append(item)

    if not req_lines:
        # No headings: treat requirement-sounding loose lines as required.
        req_lines = [(l, Priority.REQUIRED) for l in loose if _sounds_like_requirement(l)]

    requirements = [_requirement(i, text_, prio) for i, (text_, prio) in
                    enumerate(_split_items(req_lines), start=1)]
    years = _years(" ".join(t for t, _ in req_lines) or text)
    return JobDescription(
        title=title,
        company=company,
        seniority=_seniority(title, years),
        years_experience_min=years,
        responsibilities=responsibilities,
        requirements=requirements,
        raw_text=text,
    )


def _section_heading(line: str) -> str | None:
    head = line.split(":", 1)[0] if ":" in line else line
    if strip_bullet(line)[0] or len(head.split()) > 7 or head.endswith("."):
        return None
    for kind, pattern in _SECTION_PATTERNS:
        if pattern.search(head):
            return kind
    return None


def _title_and_company(lines: list[str]) -> tuple[str | None, str | None]:
    title = company = None
    for line in lines[:15]:
        if m := _LABEL_RE.match(line):
            label, value = m.group(1).lower(), m.group(2).strip()
            if label in ("company", "organization"):
                company = company or value
            else:
                title = title or value
    if title is None and lines:
        first = lines[0]
        words = re.findall(r"[a-z][a-z\-]*", first.lower())
        if len(first.split()) <= 12 and any(w in TITLE_WORDS for w in words) \
                and not _section_heading(first):
            title = first
    if title:
        # "Senior Data Analyst at Acme" / "Senior Data Analyst - Acme"
        m = re.match(r"^(.+?)\s+(?:at|@|-|–|—|\|)\s+(.+)$", title)
        if m and any(w in TITLE_WORDS for w in re.findall(r"[a-z\-]+", m.group(1).lower())):
            title, company = m.group(1).strip(), company or m.group(2).strip()
    if company is None:
        for line in lines[:10]:
            if m := re.match(r"^([A-Z][\w&.\- ]{1,40}?)\s+is\s+(hiring|looking|seeking)", line):
                company = m.group(1)
                break
    return title, company


def _company_from_about(line: str) -> str | None:
    m = re.match(r"^about\s+(.+?)[:]?$", line, re.I)
    if not m:
        return None
    name = m.group(1).strip()
    return None if name.lower() in {"us", "the role", "you", "the team", "the job"} else name


def _sounds_like_requirement(line: str) -> bool:
    return bool(
        re.search(r"\b(experience|proficien|knowledge|familiar|degree|years?|skills?|"
                  r"ability to|understanding of|expertise)\b", line, re.I)
        or find_skills(line)
    )


def _split_items(lines: list[tuple[str, Priority]]) -> list[tuple[str, Priority]]:
    """Split paragraph-style requirement lines into one item per sentence."""
    out: list[tuple[str, Priority]] = []
    for text, prio in lines:
        parts = re.split(r"(?<=[.;])\s+(?=[A-Z])", text) if len(text) > 160 else [text]
        out.extend((p.strip(), prio) for p in parts if p.strip())
    return out


def _requirement(i: int, text: str, section_priority: Priority) -> Requirement:
    priority = section_priority
    if section_priority == Priority.REQUIRED and _PLUS_WORDS.search(text):
        priority = Priority.PREFERRED  # "Experience with Kafka is a plus" under Requirements
    elif section_priority == Priority.PREFERRED and _MUST_WORDS.search(text) \
            and not _PLUS_WORDS.search(text):
        priority = Priority.REQUIRED
    keywords = find_skills(text)
    if re.search(r"certif", text, re.I):
        category = RequirementCategory.CERTIFICATION
    elif DEGREE_WORDS.search(text) and not keywords:
        category = RequirementCategory.EDUCATION
    elif keywords:
        category = RequirementCategory.SKILL
    elif _YEARS_RE.search(text) or re.search(r"\bexperience\b", text, re.I):
        category = RequirementCategory.EXPERIENCE
    else:
        category = RequirementCategory.OTHER
    return Requirement(id=f"req{i}", text=text, priority=priority, category=category,
                       keywords=keywords)


def _years(text: str) -> int | None:
    found = []
    for m in _YEARS_RE.finditer(text):
        raw = m.group(1).lower()
        found.append(int(raw) if raw.isdigit() else _NUMBER_WORDS[raw])
    # The headline requirement ("5+ years") is usually the largest number quoted.
    return max(found) if found else None


def _seniority(title: str | None, years: int | None) -> Seniority:
    if title:
        for pattern, level in _SENIORITY_WORDS:
            if pattern.search(title):
                return level
    if years is None:
        return Seniority.UNKNOWN
    if years < 2:
        return Seniority.JUNIOR
    if years < 5:
        return Seniority.MID
    return Seniority.SENIOR
