"""Interview talking points: what to be ready to say, grounded in the resume.

Three kinds, all built from things the candidate actually has:
- strength: the story behind a bullet that already matches a required item
- answer:   a confirmed answer they gave us (they'll be asked about it)
- gap:      an honest way to talk about a required item they don't have yet
"""

import re

from app.models import (
    AnswerKind,
    GapAnalysis,
    GapStatus,
    Priority,
    Resume,
    SectionKind,
    TalkingPoint,
    UpskillingPlan,
)
from app.parsing.lexicon import display_list
from app.tailoring.verifier import quantities

MAX_STRENGTHS = 3
MAX_GAPS = 2


def build_talking_points(resume: Resume, analysis: GapAnalysis,
                         plan: UpskillingPlan) -> list[TalkingPoint]:
    points: list[TalkingPoint] = []

    def add(**kw) -> None:
        points.append(TalkingPoint(id=f"tp{len(points) + 1}", **kw))

    # Stories come from work and projects, not certificate or education lines.
    storyable = {b.id for sec in resume.sections
                 if sec.kind in (SectionKind.EXPERIENCE, SectionKind.PROJECTS)
                 for e in sec.entries for b in e.bullets}
    used: set[str] = set()
    evidenced = [i for i in analysis.items if i.status == GapStatus.EVIDENCED
                 and i.evidence_bullet_ids and i.priority == Priority.REQUIRED]
    for item in evidenced:
        if sum(p.kind == "strength" for p in points) >= MAX_STRENGTHS:
            break
        bid = next((b for b in item.evidence_bullet_ids if b not in used and b in storyable), None)
        bullet = resume.bullet_by_id(bid) if bid else None
        if not bullet:
            continue
        used.add(bullet.id)
        has_number = any(q.kind != "plain" or q.value < 1900 for q in quantities(bullet.text))
        result = ("Lead with the number, and be ready to say how you measured it."
                  if has_number else
                  "If you know a real result, say it; if not, describe what changed because of your work.")
        add(kind="strength", prompt=f'Tell the story behind "{bullet.text}"',
            detail=f"Set the scene in a sentence, say what you did yourself, then the outcome. {result}",
            bullet_ids=[bullet.id], requirement_ids=[item.requirement_id])

    for item in analysis.items:
        q = item.question
        if q and q.answer and q.answer_kind == AnswerKind.CONFIRMED:
            add(kind="answer", prompt=f"Be ready to go deeper on: {item.requirement_text}",
                detail=f'You told us: "{q.answer}" Expect follow-ups on what exactly you did and '
                       f"what you'd do differently.",
                requirement_ids=[item.requirement_id])

    gaps = [i for i in analysis.items if i.status == GapStatus.MISSING
            and i.priority == Priority.REQUIRED
            and not (i.question and i.question.answer_kind == AnswerKind.CONFIRMED)]
    for item in gaps[:MAX_GAPS]:
        joiner = "or" if re.search(r"\bor\b", item.requirement_text, re.I) else "and"
        name = display_list(item.missing_keywords, joiner) or item.requirement_text
        learning = [k for k in item.missing_keywords if k in plan.focus_skills]
        plan_note = (" Mention that you've started learning it, and what you built in your "
                     "two-week plan, once that's true." if learning else "")
        add(kind="gap", prompt=f"If they ask about {name}",
            detail=f"Say plainly that you haven't used it in a job yet. Then point to the closest "
                   f"thing you have done and how you'd ramp up.{plan_note}",
            requirement_ids=[item.requirement_id])
    return points
