"""Hybrid ATS score. Five of six components are deterministic; semantic relevance
uses Claude when available and a word-overlap proxy otherwise.

Weights (models/ats.py): required keywords 40, preferred 10, semantic 20,
title/seniority 10, format 10, quantified impact 10.
"""

import re
from datetime import date

from app.analysis.experience import years_of_experience
from app.llm.client import LLM
from app.models import (
    ATSReport,
    Component,
    JobDescription,
    ParseWarningCode,
    Priority,
    Resume,
    ScoreComponent,
    SectionKind,
)
from app.parsing.jd_parser import SENIORITY_ORDER, infer_seniority, keyword_groups
from app.parsing.lexicon import IMPLIES, find_skills
from app.parsing.text import content_words
from app.tailoring.apply import render_text
from app.tailoring.verifier import quantities

from .semantic import semantic_component


def score(resume: Resume, jd: JobDescription, *, llm: LLM | None = None,
          today: date | None = None) -> ATSReport:
    text = render_text(resume)
    found = set(find_skills(text))
    in_bullets = set(find_skills(" ".join(b.text for b in resume.bullets())))
    return ATSReport(components=[
        keyword_component(Component.REQUIRED_KEYWORDS, Priority.REQUIRED, jd, found, in_bullets),
        keyword_component(Component.PREFERRED_KEYWORDS, Priority.PREFERRED, jd, found,
                          in_bullets),
        semantic_component(resume, jd, llm),
        title_component(resume, jd, today),
        format_component(resume),
        impact_component(resume),
    ])


# --- keywords --------------------------------------------------------------------------


def keyword_component(name: Component, priority: Priority, jd: JobDescription,
                      found: set[str], in_bullets: set[str]) -> ScoreComponent:
    groups: list[list[str]] = []
    for req in jd.requirements:
        if req.priority == priority:
            for g in keyword_groups(req):
                if g not in groups:
                    groups.append(g)
    if not groups:
        return ScoreComponent(name=name, score=1.0,
                              notes=f"The JD lists no recognizable {priority.value} keywords.")
    matched, missing, notes = [], [], []
    for g in groups:
        hit = [k for k in g if k in found]
        label = " / ".join(g)
        if hit:
            matched.append(label)
        else:
            missing.append(label)
            via = sorted({s for k in g for s in found if k in IMPLIES.get(s, [])})
            if via:
                notes.append(f"{label} is implied by {', '.join(via)}, but an ATS only "
                             f"counts the exact term. Name it only if it's true.")
    skills_only = sorted({k for g in groups for k in g if k in found and k not in in_bullets})
    if skills_only:
        notes.append(f"Only in your Skills list, not in any bullet: {', '.join(skills_only)}. "
                     f"Recruiters look for evidence of use.")
    return ScoreComponent(name=name, score=round(len(matched) / len(groups), 3),
                          matched=matched, missing=missing, notes=" ".join(notes))


# --- title / seniority --------------------------------------------------------------------

_ROLE_FAMILIES = [
    {"engineer", "developer", "programmer", "sde", "swe"}, {"analyst"}, {"scientist"},
    {"manager"}, {"designer"}, {"consultant"}, {"architect"}, {"administrator", "admin"},
    {"specialist"}, {"researcher"}, {"intern"}, {"director"}, {"coordinator"},
]
_SENIORITY_WORDS = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "ii", "iii",
                    "iv", "i", "associate", "head", "chief", "entry", "level", "mid"}


def _title_parts(title: str) -> tuple[set[int], set[str]]:
    words = re.findall(r"[a-z]+", title.lower())
    roles = {i for i, fam in enumerate(_ROLE_FAMILIES) for w in words if w in fam}
    role_words = set().union(*_ROLE_FAMILIES)
    domain = content_words(" ".join(w for w in words
                                    if w not in role_words and w not in _SENIORITY_WORDS))
    return roles, domain


def title_similarity(jd_title: str, cand_title: str) -> float:
    jr, jdom = _title_parts(jd_title)
    cr, cdom = _title_parts(cand_title)
    domain = 1.0 if not jdom else len(jdom & cdom) / len(jdom | cdom) if cdom else 0.0
    if jr & cr:
        return round(0.6 + 0.4 * domain, 3)
    return round(0.3 * domain, 3)


def title_component(resume: Resume, jd: JobDescription, today: date | None) -> ScoreComponent:
    titles = [e.title for s in resume.sections if s.kind == SectionKind.EXPERIENCE
              for e in s.entries if e.title]
    notes = []
    if not jd.title:
        title_score = 1.0
        notes.append("The JD has no clear title, so title match isn't scored.")
    elif not titles:
        title_score = 0.0
        notes.append("No job titles found in your Experience section.")
    else:
        scored = [(title_similarity(jd.title, t) * (1.0 if i == 0 else 0.85), t)
                  for i, t in enumerate(titles)]
        title_score, best = max(scored)
        notes.append(f'Closest title: "{best}" vs "{jd.title}".')

    years = years_of_experience(resume, today=today)
    cand = infer_seniority(titles[0] if titles else None, years)
    if jd.seniority.value == "unknown":
        sen_score = 1.0
    elif cand.value == "unknown":
        sen_score = 0.5
        notes.append("Couldn't infer your seniority (no dated roles).")
    else:
        gap = SENIORITY_ORDER.index(jd.seniority) - SENIORITY_ORDER.index(cand)
        sen_score = 1.0 if gap <= 0 else 0.5 if gap == 1 else 0.0
        yrs = f", about {years:g} years" if years is not None else ""
        notes.append(f"Role is {jd.seniority.value}; your resume reads as {cand.value}{yrs}.")
    total = round(0.5 * title_score + 0.5 * sen_score, 3)
    return ScoreComponent(name=Component.TITLE_SENIORITY, score=total,
                          matched=[f"seniority: {cand.value}"] if sen_score == 1.0 else [],
                          missing=[f"seniority: {jd.seniority.value}"] if sen_score < 1.0
                          else [], notes=" ".join(notes))


# --- format / parseability ------------------------------------------------------------------

_DEDUCTIONS = {
    ParseWarningCode.MULTI_COLUMN_SUSPECTED: 0.3,
    ParseWarningCode.NO_SECTIONS_FOUND: 0.3,
    ParseWarningCode.TABLES_DETECTED: 0.2,
    ParseWarningCode.NO_BULLETS_FOUND: 0.2,
    ParseWarningCode.CONTACT_MISSING: 0.2,
    ParseWarningCode.IMAGES_DETECTED: 0.1,
    ParseWarningCode.NAME_NOT_FOUND: 0.1,
}


def format_component(resume: Resume) -> ScoreComponent:
    s = 1.0
    missing: list[str] = []
    for w in resume.parse_warnings:
        s -= _DEDUCTIONS.get(w.code, 0.0)
        missing.append(w.message)
    kinds = {sec.kind for sec in resume.sections}
    for kind, label in [(SectionKind.EXPERIENCE, "Experience"),
                        (SectionKind.EDUCATION, "Education")]:
        if kind not in kinds:
            s -= 0.1
            missing.append(f"No {label} section.")
    if not resume.skills:
        s -= 0.05
        missing.append("No Skills section.")
    exp = [e for sec in resume.sections if sec.kind == SectionKind.EXPERIENCE
           for e in sec.entries]
    undated = [e for e in exp if not (e.start_date or e.end_date)]
    if undated:
        s -= 0.1
        missing.append(f"{len(undated)} role(s) without dates.")
    long = [b.id for b in resume.bullets() if len(b.text.split()) > 40]
    if long:
        s -= 0.05
        missing.append(f"{len(long)} bullet(s) over 40 words.")
    matched = [] if missing else ["Single column, standard headings, dated roles, "
                                  "plain bullets."]
    return ScoreComponent(name=Component.FORMAT_PARSEABILITY, score=round(max(s, 0.0), 3),
                          matched=matched, missing=missing)


# --- quantified impact --------------------------------------------------------------------------

_TARGET_SHARE = 0.5  # half the bullets with a number scores full marks


def _has_metric(text: str) -> bool:
    return any(not (q.kind == "plain" and 1900 <= q.value <= 2100) for q in quantities(text))


def impact_component(resume: Resume) -> ScoreComponent:
    bullets = [b for sec in resume.sections
               if sec.kind in (SectionKind.EXPERIENCE, SectionKind.PROJECTS)
               for e in sec.entries for b in e.bullets]
    if not bullets:
        return ScoreComponent(name=Component.QUANTIFIED_IMPACT, score=0.0,
                              notes="No experience or project bullets to measure.")
    with_n = [b.id for b in bullets if _has_metric(b.text)]
    share = len(with_n) / len(bullets)
    return ScoreComponent(
        name=Component.QUANTIFIED_IMPACT, score=round(min(1.0, share / _TARGET_SHARE), 3),
        matched=with_n, missing=[b.id for b in bullets if b.id not in with_n],
        notes=f"{len(with_n)} of {len(bullets)} bullets include a number. Add real metrics "
              f"you can stand behind; never estimate ones you don't know.")
