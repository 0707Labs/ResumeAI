"""Total years of experience from entry date ranges, with overlaps merged."""

import re
from datetime import date

from app.models import Entry, Resume, SectionKind

_MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}
_OPEN = re.compile(r"present|current|now|ongoing|date", re.I)


def parse_month(text: str | None, *, is_end: bool, today: date) -> int | None:
    """Months since year 0 (year*12 + month-1), or None if unparseable."""
    if not text:
        return None
    t = text.strip().lower()
    if _OPEN.search(t):
        return today.year * 12 + today.month - 1
    if m := re.match(r"^(\d{1,2})/(\d{4})$", t):
        return int(m.group(2)) * 12 + int(m.group(1)) - 1
    if m := re.match(r"^([a-z]{3})[a-z]*\.?\s*'?(\d{2,4})$", t):
        month = _MONTHS.get(m.group(1))
        year = int(m.group(2))
        year += 2000 if year < 100 else 0
        return year * 12 + month - 1 if month else None
    if m := re.match(r"^(\d{4})$", t):
        return int(m.group(1)) * 12 + (11 if is_end else 0)
    return None


def is_internship(entry: Entry) -> bool:
    return bool(entry.title and re.search(r"\bintern(ship)?\b", entry.title, re.I))


def years_of_experience(resume: Resume, today: date | None = None) -> float | None:
    """Merged span of non-internship experience entries, in years (1 decimal).
    None when no experience entry has parseable dates."""
    today = today or date.today()
    spans: list[tuple[int, int]] = []
    for section in resume.sections:
        if section.kind != SectionKind.EXPERIENCE:
            continue
        for entry in section.entries:
            if is_internship(entry):
                continue
            start = parse_month(entry.start_date, is_end=False, today=today)
            end = parse_month(entry.end_date, is_end=True, today=today)
            if start is not None and end is not None and end >= start:
                spans.append((start, end + 1))  # end month inclusive
    if not spans:
        return None
    spans.sort()
    total, (cur_s, cur_e) = 0, spans[0]
    for s, e in spans[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    total += cur_e - cur_s
    return round(total / 12, 1)
