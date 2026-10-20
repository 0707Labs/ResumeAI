"""Gap analysis: classify each JD requirement as Evidenced / Implied / Missing.

The rules pass is deterministic. It is deliberately conservative: only an exact
skill mention (in a bullet, the Skills list, or the summary) counts as
EVIDENCED. Related skills, job titles, and word overlap are at most IMPLIED.
An optional LLM pass (see refine.py) may only look at items the rules could not
settle and may only move them between MISSING and IMPLIED.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from app.models import (
    GapAnalysis,
    GapItem,
    GapStatus,
    JobDescription,
    Priority,
    Requirement,
    RequirementCategory,
    Resume,
    SectionKind,
)
from app.parsing.jd_parser import keyword_groups
from app.parsing.lexicon import DEGREE_WORDS, IMPLIES, find_skills
from app.parsing.text import content_words

from .experience import years_of_experience
from .questions import assign_questions

_YEARS_RE = re.compile(
    r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s*\+?\s*"
    r"(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)", re.I)
_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten".split())}

# Job titles that say a skill outright ("Data Analyst" does data analysis).
_TITLE_IMPLIES: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"\b(data|business|product|marketing|reporting) analyst\b", re.I),
     ["data analysis"]),
    (re.compile(r"\bdata engineer\b", re.I), ["etl"]),
    (re.compile(r"\b(machine learning|ml) engineer\b", re.I), ["machine learning"]),
    (re.compile(r"\bproduct manager\b", re.I), ["product management"]),
    (re.compile(r"\bproject manager\b", re.I), ["project management"]),
]

_DEGREE_LEVELS: list[tuple[re.Pattern[str], int, str]] = [
    (re.compile(r"\b(ph\.?d|doctorate|doctoral)\b", re.I), 4, "doctorate"),
    (re.compile(r"\b(master'?s?|mba|m\.?\s?tech|m\.?sc?|m\.?a\.?|m\.?s\.?|msc)\b", re.I), 3,
     "master's"),
    (re.compile(r"\b(bachelor'?s?|b\.?\s?tech|b\.?e\.?|b\.?sc?|b\.?a\.?|b\.?s\.?|bsc|"
                r"undergraduate)\b", re.I), 2, "bachelor's"),
    (re.compile(r"\bassociate'?s? degree\b", re.I), 1, "associate"),
    (re.compile(r"\bdiploma\b", re.I), 0, "diploma"),
]

@dataclass
class _Evidence:
    bullets: list[str] = field(default_factory=list)  # bullet ids naming the skill
    stated: bool = False  # in Skills list or summary
    implied_bullets: list[str] = field(default_factory=list)
    implied_entries: list[str] = field(default_factory=list)
    implied_via: list[str] = field(default_factory=list)


@dataclass
class _Index:
    """Pre-computed skill mentions across the resume."""

    resume: Resume
    bullet_skills: dict[str, list[str]]  # bullet id -> canonical skills
    stated_skills: set[str]
    entry_title_skills: dict[str, list[str]]  # entry id -> skills its title implies

    @classmethod
    def build(cls, resume: Resume) -> "_Index":
        bullet_skills = {b.id: find_skills(b.text) for b in resume.bullets()}
        stated = set(find_skills(" ; ".join(resume.skills)))
        if resume.summary:
            stated |= set(find_skills(resume.summary))
        titles: dict[str, list[str]] = {}
        for entry in resume.entries():
            implied = [s for pat, skills in _TITLE_IMPLIES if entry.title and
                       pat.search(entry.title) for s in skills]
            if implied:
                titles[entry.id] = implied
        return cls(resume, bullet_skills, stated, titles)

    def evidence_for(self, skill: str) -> _Evidence:
        ev = _Evidence()
        for bid, skills in self.bullet_skills.items():
            if skill in skills:
                ev.bullets.append(bid)
            else:
                via = [s for s in skills if skill in IMPLIES.get(s, [])]
                if via:
                    ev.implied_bullets.append(bid)
                    ev.implied_via.extend(v for v in via if v not in ev.implied_via)
        ev.stated = skill in self.stated_skills
        if not ev.stated:
            via = [s for s in self.stated_skills if skill in IMPLIES.get(s, [])]
            ev.implied_via.extend(v for v in via if v not in ev.implied_via)
        for eid, skills in self.entry_title_skills.items():
            if skill in skills:
                ev.implied_entries.append(eid)
        return ev


def analyze(resume: Resume, jd: JobDescription, today: date | None = None) -> GapAnalysis:
    index = _Index.build(resume)
    years = years_of_experience(resume, today=today)
    items = [_classify(req, index, years) for req in jd.requirements]
    items = assign_questions(items, resume)
    return GapAnalysis(items=items, candidate_years_experience=years)


def _classify(req: Requirement, index: _Index, years: float | None) -> GapItem:
    base = dict(requirement_id=req.id, requirement_text=req.text, priority=req.priority,
                category=req.category)
    if req.keywords:
        item = _classify_keywords(req, index, base)
    elif req.category == RequirementCategory.EDUCATION:
        item = _classify_degree(req, index.resume, base)
    elif req.category == RequirementCategory.CERTIFICATION:
        item = _classify_certification(req, index.resume, base)
    else:
        item = _classify_overlap(req, index.resume, base)
    needed = _years_required(req.text)
    if needed is not None:
        item = _apply_years(item, needed, years)
    return item


def _classify_keywords(req: Requirement, index: _Index, base: dict) -> GapItem:
    any_of = len(keyword_groups(req)) == 1 and len(req.keywords) > 1
    per_kw = {kw: index.evidence_for(kw) for kw in req.keywords}
    direct = [kw for kw, ev in per_kw.items() if ev.bullets or ev.stated]
    implied = [kw for kw, ev in per_kw.items() if kw not in direct and
               (ev.implied_bullets or ev.implied_entries or ev.implied_via)]
    missing = [kw for kw in req.keywords if kw not in direct and kw not in implied]

    bullet_ids = _dedupe(b for kw in direct for b in per_kw[kw].bullets)
    stated = [kw for kw in direct if per_kw[kw].stated and not per_kw[kw].bullets]
    implied_bullets = _dedupe(b for kw in implied for b in per_kw[kw].implied_bullets)
    implied_entries = _dedupe(e for kw in implied for e in per_kw[kw].implied_entries)
    implied_stated = _dedupe(v for kw in implied for v in per_kw[kw].implied_via
                             if v in index.stated_skills and not per_kw[kw].implied_bullets)

    complete = bool(direct) if any_of else not (implied or missing)
    if complete:
        status = GapStatus.EVIDENCED
        rationale = _evidenced_rationale(direct, per_kw)
        missing_out: list[str] = []
        implied_bullets, implied_entries, implied_stated = [], [], []
    elif direct or implied:
        status = GapStatus.IMPLIED
        parts = []
        if direct:
            parts.append(f"shown: {', '.join(direct)}")
        if implied:
            vias = _dedupe(v for kw in implied for v in per_kw[kw].implied_via)
            via = f" (via {', '.join(vias)})" if vias else " (via job title)"
            parts.append(f"suggested but not named: {', '.join(implied)}{via}")
        if missing:
            parts.append(f"not found: {', '.join(missing)}")
        rationale = _sentence("; ".join(parts))
        missing_out = implied + missing
    else:
        status = GapStatus.MISSING
        rationale = f"No mention of {', '.join(missing)} anywhere in the resume."
        missing_out = missing

    return GapItem(
        **base, status=status,
        evidence_bullet_ids=_dedupe([*bullet_ids, *implied_bullets]),
        evidence_entry_ids=implied_entries,
        evidence_skills=_dedupe([*stated, *implied_stated]),
        matched_keywords=direct, missing_keywords=missing_out, rationale=rationale,
        question=_placeholder(req.id) if status == GapStatus.MISSING else None,
    )


def _evidenced_rationale(direct: list[str], per_kw: dict[str, _Evidence]) -> str:
    in_bullets = [kw for kw in direct if per_kw[kw].bullets]
    only_listed = [kw for kw in direct if not per_kw[kw].bullets]
    parts = []
    if in_bullets:
        parts.append(f"{', '.join(in_bullets)} named in your bullets")
    if only_listed:
        parts.append(f"{', '.join(only_listed)} listed in Skills/summary but not shown in "
                     f"any bullet")
    return _sentence("; ".join(parts))


def _years_required(text: str) -> int | None:
    m = _YEARS_RE.search(text)
    if not m:
        return None
    raw = m.group(1).lower()
    return int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]


def _apply_years(item: GapItem, needed: int, have: float | None) -> GapItem:
    if have is not None and have >= needed:
        note = f" About {have:g} years of dated experience meets the {needed}+ asked."
        return item.model_copy(update={"rationale": (item.rationale + note).strip()})
    have_txt = "no dated non-internship roles" if have is None else f"about {have:g} years"
    note = f" Asks for {needed}+ years; your resume shows {have_txt}."
    rationale = (item.rationale + note).strip()
    if item.status == GapStatus.EVIDENCED:
        # The skill is there but the tenure isn't: downgrade, never upgrade.
        return item.model_copy(update={"status": GapStatus.IMPLIED, "rationale": rationale})
    if item.status == GapStatus.IMPLIED:
        return item.model_copy(update={"rationale": rationale})
    return item.model_copy(update={"rationale": rationale,
                                   "question": item.question or _placeholder(item.requirement_id)})


def _degree_level(text: str) -> tuple[int, str] | None:
    for pattern, level, name in _DEGREE_LEVELS:
        if pattern.search(text):
            return level, name
    return None


def degree_meets(req: Requirement, resume: Resume) -> bool:
    item = _classify_degree(req, resume, dict(requirement_id=req.id,
                                               requirement_text=req.text))
    return item.status == GapStatus.EVIDENCED


def _classify_degree(req: Requirement, resume: Resume, base: dict) -> GapItem:
    needed = _degree_level(req.text)
    best: tuple[int, str, str] | None = None  # level, name, entry id
    for section in resume.sections:
        if section.kind != SectionKind.EDUCATION:
            continue
        for entry in section.entries:
            text = " ".join(filter(None, [entry.title, entry.organization]))
            lvl = _degree_level(text) if DEGREE_WORDS.search(text) else None
            if lvl and (best is None or lvl[0] > best[0]):
                best = (lvl[0], lvl[1], entry.id)
    if best and (needed is None or best[0] >= needed[0]):
        return GapItem(**base, status=GapStatus.EVIDENCED, evidence_entry_ids=[best[2]],
                       rationale=f"Your {best[1]} degree meets the level asked. "
                                 f"Field of study isn't checked automatically.")
    if best:
        why = f"Asks for a {needed[1]} degree; your highest listed is a {best[1]}."
    else:
        why = "No degree found in an Education section."
    return GapItem(**base, status=GapStatus.MISSING, rationale=why,
                   question=_placeholder(req.id))


def _classify_certification(req: Requirement, resume: Resume, base: dict) -> GapItem:
    want = content_words(req.text) - {"certif", "certificate", "certification", "certified"}
    best_id, best = None, 0.0
    for section in resume.sections:
        if section.kind != SectionKind.CERTIFICATIONS:
            continue
        for entry in section.entries:
            for b in entry.bullets:
                score = len(want & content_words(b.text)) / max(len(want), 1)
                if score > best:
                    best_id, best = b.id, score
    if best_id and best >= 0.6:
        return GapItem(**base, status=GapStatus.EVIDENCED, evidence_bullet_ids=[best_id],
                       rationale="Matching certification listed.")
    return GapItem(**base, status=GapStatus.MISSING, rationale="No matching certification "
                   "listed.", question=_placeholder(req.id))


def _classify_overlap(req: Requirement, resume: Resume, base: dict) -> GapItem:
    """Requirements with no known skill keywords ("mentor junior analysts"):
    word overlap can suggest IMPLIED; it can never prove EVIDENCED."""
    want = content_words(req.text)
    scored = []
    for b in resume.bullets():
        shared = want & content_words(b.text)
        if len(shared) >= 2 and len(shared) / max(len(want), 1) >= 0.4:
            scored.append((len(shared), b.id, shared))
    if scored:
        scored.sort(reverse=True)
        ids = [bid for _, bid, _ in scored[:3]]
        shared = sorted(set().union(*(s for _, _, s in scored[:3])))
        return GapItem(**base, status=GapStatus.IMPLIED, evidence_bullet_ids=ids,
                       rationale=f"Related wording in your bullets ({', '.join(shared)}); "
                                 f"worth confirming.", decided_by="rules-fuzzy")
    return GapItem(**base, status=GapStatus.MISSING,
                   rationale="Nothing in the resume clearly addresses this.",
                   question=_placeholder(req.id))


def _placeholder(req_id: str):
    # Real wording and ids are filled in by assign_questions once all items exist.
    from app.models import ClarifyingQuestion

    return ClarifyingQuestion(id="q0", requirement_id=req_id, question="pending")


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] + "."


def _dedupe(items) -> list:
    out: list = []
    for x in items:
        if x not in out:
            out.append(x)
    return out
