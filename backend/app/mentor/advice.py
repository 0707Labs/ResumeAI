"""Mentor advice: strengths -> gaps -> actions -> verdict -> 2-week plan.

All rules-based, built from the gap analysis and ATS report, so every strength
cites a real bullet and every gap names a real requirement. Claude can optionally
reword it (polish.py) but can't change the structure or the verdict.
"""

import re
from datetime import date

from app.analysis.experience import years_of_experience
from app.models import (
    ATSReport,
    Action,
    ActionKind,
    AnswerKind,
    Component,
    Decision,
    GapAnalysis,
    GapItem,
    GapSeverity,
    GapStatus,
    JobDescription,
    MentorAdvice,
    MentorGap,
    Priority,
    RequirementCategory,
    Resume,
    Strength,
    Verdict,
)
from app.parsing.jd_parser import SENIORITY_ORDER, infer_seniority
from app.parsing.lexicon import display_list

from .plan import build_plan
from .talking_points import build_talking_points

MAX_STRENGTHS = 5
MAX_METRIC_EDITS = 3


def build_advice(resume: Resume, jd: JobDescription, analysis: GapAnalysis, ats: ATSReport,
                 today: date | None = None) -> MentorAdvice:
    strengths = _strengths(resume, analysis, ats)
    gaps = _gaps(analysis, ats)
    seniority_gap = _seniority_gap(resume, jd, today)
    verdict = _verdict(analysis, ats, gaps, seniority_gap, jd)
    plan = build_plan(analysis)
    actions = _actions(resume, analysis, ats, verdict, plan.focus_skills)
    return MentorAdvice(strengths=strengths, gaps=gaps, actions=actions, verdict=verdict,
                        plan=plan, talking_points=build_talking_points(resume, analysis, plan),
                        notes=["Rules-based advice."])


# --- strengths ---------------------------------------------------------------------------


def _strengths(resume: Resume, analysis: GapAnalysis, ats: ATSReport) -> list[Strength]:
    out: list[Strength] = []
    evidenced = [i for i in analysis.items if i.status == GapStatus.EVIDENCED]
    evidenced.sort(key=lambda i: (i.priority != Priority.REQUIRED, not i.evidence_bullet_ids))
    for item in evidenced:
        if len(out) >= MAX_STRENGTHS - 1:
            break
        bullet = resume.bullet_by_id(item.evidence_bullet_ids[0]) \
            if item.evidence_bullet_ids else None
        what = display_list(item.matched_keywords) or _short(item.requirement_text, 60)
        if bullet:
            text = f'{_cap(what)}: shown directly in "{bullet.text}".'
        elif item.category == RequirementCategory.EDUCATION:
            text = f"Your degree meets the bar: {_short(item.requirement_text, 70)}."
        else:
            text = f"{_cap(what)}: listed on your resume ({item.rationale.rstrip('.')})."
        out.append(Strength(text=text, evidence_bullet_ids=item.evidence_bullet_ids[:2],
                            requirement_ids=[item.requirement_id]))
    comps = {c.name: c for c in ats.components}
    impact = comps[Component.QUANTIFIED_IMPACT]
    if impact.score >= 0.8 and impact.matched:
        out.append(Strength(text=f"You quantify your impact: {len(impact.matched)} bullets "
                                 f"carry real numbers.", evidence_bullet_ids=impact.matched[:3]))
    elif comps[Component.FORMAT_PARSEABILITY].score >= 0.95 and len(out) < MAX_STRENGTHS:
        out.append(Strength(text="Clean, ATS-friendly format: standard headings, single "
                                 "column, dated roles."))
    return out[:MAX_STRENGTHS]


# --- gaps --------------------------------------------------------------------------------------


def _answer_kind(item: GapItem) -> AnswerKind:
    return item.question.answer_kind if item.question else AnswerKind.UNANSWERED


def _severity(item: GapItem) -> GapSeverity:
    if _answer_kind(item) == AnswerKind.CONFIRMED:
        return GapSeverity.MINOR  # the candidate has it; the resume just didn't say so
    if item.priority == Priority.PREFERRED:
        return GapSeverity.MINOR
    return GapSeverity.CRITICAL if item.status == GapStatus.MISSING else GapSeverity.MODERATE


def _gaps(analysis: GapAnalysis, ats: ATSReport) -> list[MentorGap]:
    out: list[MentorGap] = []
    for item in analysis.items:
        if item.status == GapStatus.EVIDENCED:
            continue
        sev = _severity(item)
        kind = _answer_kind(item)
        joiner = "or" if re.search(r"\bor\b", item.requirement_text, re.I) else "and"
        what = display_list(item.missing_keywords, joiner) or _short(item.requirement_text, 70)
        if kind == AnswerKind.CONFIRMED:
            why = (f"You said you have this. Make sure a tailored bullet cites your answer, "
                   f"or the ATS and the recruiter won't see it.")
        elif kind == AnswerKind.DECLINED:
            why = ("You said you don't have this yet. Be ready to say so honestly and show "
                   "how you'd ramp up.")
        elif item.status == GapStatus.IMPLIED:
            why = (f"Your resume hints at {what} but never names it. ATS filters match exact "
                   f"terms, so it may not count.")
        else:
            why = ("It's listed as required, so recruiters and ATS filters will look for it."
                   if item.priority == Priority.REQUIRED else
                   "Nice to have. It won't sink you, but it can break a tie.")
        text = what if item.missing_keywords else _cap(what)  # keep "dbt", "pandas"
        out.append(MentorGap(requirement_id=item.requirement_id, text=text,
                             priority=item.priority, status=item.status, severity=sev,
                             why_it_matters=why))
    impact = next(c for c in ats.components if c.name == Component.QUANTIFIED_IMPACT)
    if impact.score < 0.6 and impact.missing:
        out.append(MentorGap(text="Few bullets show measurable results",
                             severity=GapSeverity.MODERATE,
                             why_it_matters="Numbers (time saved, volume, accuracy) are what "
                                            "make a bullet credible to a recruiter."))
    fmt = next(c for c in ats.components if c.name == Component.FORMAT_PARSEABILITY)
    if fmt.score < 0.8:
        out.append(MentorGap(text="Formatting may trip up ATS parsers",
                             severity=GapSeverity.MODERATE,
                             why_it_matters="; ".join(fmt.missing[:3]) or fmt.notes))
    order = {GapSeverity.CRITICAL: 0, GapSeverity.MODERATE: 1, GapSeverity.MINOR: 2}
    return sorted(out, key=lambda g: order[g.severity])


# --- verdict ----------------------------------------------------------------------------------


def _seniority_gap(resume: Resume, jd: JobDescription, today: date | None) -> int | None:
    if jd.seniority.value == "unknown":
        return None
    titles = [e.title for e in resume.entries() if e.title]
    cand = infer_seniority(titles[0] if titles else None,
                           years_of_experience(resume, today=today))
    if cand.value == "unknown":
        return None
    return SENIORITY_ORDER.index(jd.seniority) - SENIORITY_ORDER.index(cand)


def _verdict(analysis: GapAnalysis, ats: ATSReport, gaps: list[MentorGap],
             seniority_gap: int | None, jd: JobDescription) -> Verdict:
    cov = analysis.required_coverage
    critical = sum(1 for g in gaps if g.severity == GapSeverity.CRITICAL and g.requirement_id)
    sen = seniority_gap if seniority_gap is not None else 0
    total = ats.total

    reasons = [f"You cover about {round(cov * 100)}% of the required items "
               f"(implied ones count half).",
               f"Estimated ATS match: {total:g}/100."]
    if critical:
        names = [g.text for g in gaps if g.severity == GapSeverity.CRITICAL and
                 g.requirement_id][:3]
        reasons.append(f"{critical} required item(s) have nothing behind them yet: "
                       f"{'; '.join(names)}.")
    if seniority_gap is not None and seniority_gap > 0:
        reasons.append(f"The role is {jd.seniority.value}; your experience reads "
                       f"{seniority_gap} level(s) below that.")

    if cov >= 0.85 and critical == 0 and sen <= 0 and total >= 75:
        decision, headline = Decision.STRONG_FIT, "Apply now. You're a strong match."
    elif cov >= 0.7 and critical <= 1 and sen <= 1:
        decision, headline = Decision.APPLY, ("Apply. Make the quick fixes below first so "
                                              "the match is visible.")
    elif cov >= 0.45 and sen <= 2:
        decision, headline = Decision.STRETCH, ("Worth applying as a stretch. Lead with your "
                                                "strengths and be upfront about the gaps.")
    else:
        decision, headline = Decision.NOT_YET, ("Not yet. Close the biggest gaps first, or "
                                                "look for a role one step closer.")
    return Verdict(decision=decision, headline=headline, reasons=reasons)


# --- actions ------------------------------------------------------------------------------------


def _actions(resume: Resume, analysis: GapAnalysis, ats: ATSReport, verdict: Verdict,
             focus_skills: list[str]) -> list[Action]:
    actions: list[Action] = []

    def add(kind, text, effort, **kw):
        actions.append(Action(id=f"a{len(actions) + 1}", kind=kind, text=text, effort=effort,
                              **kw))

    # 1. Unanswered questions on required items: the cheapest win there is.
    open_qs = [i for i in analysis.items if i.question and
               _answer_kind(i) == AnswerKind.UNANSWERED]
    open_qs.sort(key=lambda i: (i.priority != Priority.REQUIRED, i.status != GapStatus.MISSING))
    for item in open_qs[:4]:
        add(ActionKind.ANSWER_QUESTION,
            f'Answer question {item.question.id} about "{_short(item.requirement_text, 60)}". '
            f"If you've done it, tailoring can use it. If not, saying no is fine.",
            "5 min", requirement_ids=[item.requirement_id], question_id=item.question.id)

    # 2. Confirmed answers that need a bullet.
    for item in analysis.items:
        if _answer_kind(item) == AnswerKind.CONFIRMED and item.status != GapStatus.EVIDENCED:
            add(ActionKind.RESUME_EDIT,
                f"Put your answer to {item.question.id} ({_short(item.requirement_text, 50)}) "
                f"into a bullet: re-tailor with Claude on, or edit the related bullet and cite "
                f"the answer.", "5 min",
                requirement_ids=[item.requirement_id], question_id=item.question.id)

    # 3. Metrics: only real ones.
    impact = next(c for c in ats.components if c.name == Component.QUANTIFIED_IMPACT)
    for bid in impact.missing[:MAX_METRIC_EDITS]:
        bullet = resume.bullet_by_id(bid)
        if bullet:
            add(ActionKind.RESUME_EDIT,
                f'If you know a real number for "{_short(bullet.text, 70)}" (time saved, '
                f"volume, users, error rate), add it. Don't estimate one you can't back up.",
                "10 min", bullet_ids=[bid])

    # 4. Skills listed but never shown.
    req = next(c for c in ats.components if c.name == Component.REQUIRED_KEYWORDS)
    if "Only in your Skills list" in req.notes:
        add(ActionKind.RESUME_EDIT,
            "Some required skills appear only in your Skills list. Answer the matching "
            "questions with where you used them, so a bullet can show it.", "10 min")

    # 5. Format fixes.
    fmt = next(c for c in ats.components if c.name == Component.FORMAT_PARSEABILITY)
    for issue in fmt.missing[:2]:
        add(ActionKind.RESUME_EDIT, f"Fix formatting: {issue}", "15 min")

    # 6. Learning, tied to the plan.
    if focus_skills:
        add(ActionKind.LEARN,
            f"Follow the 2-week plan for {display_list(focus_skills)} and finish its project. "
            f"Add the project to your resume only once it's done.", "1-2 h/day",
            requirement_ids=[i.requirement_id for i in analysis.items
                             if set(i.missing_keywords) & set(focus_skills)])

    # 7. Application strategy.
    if verdict.decision in (Decision.STRETCH, Decision.APPLY):
        add(ActionKind.APPLY_STRATEGY,
            "In your cover letter or recruiter note, name your top gap and what you're doing "
            "about it. Honesty about a gap reads better than hoping no one notices.", "20 min")
    if verdict.decision in (Decision.STRETCH, Decision.NOT_YET):
        add(ActionKind.APPLY_STRATEGY,
            "Look for a referral. A warm intro gets a stretch application read by a person "
            "rather than filtered out.", "30 min")
    return actions


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]
