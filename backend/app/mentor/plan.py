"""A realistic 2-week (10 working days, 1-2 h/day) upskilling plan.

Focuses on at most three learnable skill gaps, required first. It ends with a small,
real project, which is the only honest way to turn a gap into a resume line.
Years of experience and degrees can't be closed in two weeks; those are listed
separately rather than pretended away.
"""

import re

from app.models import (
    AnswerKind,
    GapAnalysis,
    GapItem,
    GapStatus,
    PlanTask,
    PlanWeek,
    Priority,
    RequirementCategory,
    UpskillingPlan,
)
from app.parsing.lexicon import display_list, display_name

MAX_FOCUS = 3

# Where to start for common skills. Kept generic (official docs and tutorials) so
# links don't rot; the default covers everything else.
RESOURCES: dict[str, str] = {
    "python": "the official Python tutorial (docs.python.org), then rewrite one of your "
              "spreadsheet tasks as a script",
    "sql": "SQLBolt or Mode's SQL tutorial, focusing on joins, GROUP BY, and window functions",
    "statistics": "Khan Academy statistics (distributions, confidence intervals, hypothesis "
                  "tests)",
    "a/b testing": "an online A/B testing course or Evan Miller's sample-size articles, then "
                   "analyze a public experiment dataset",
    "airflow": "the Apache Airflow tutorial: install locally and write a DAG with 2-3 tasks",
    "dbt": "the dbt Fundamentals course (free, from dbt Labs) using its sample project",
    "snowflake": "a Snowflake free trial with its 'Zero to Snowflake' quickstart",
    "bigquery": "the BigQuery sandbox (free, no card) with a public dataset",
    "tableau": "Tableau Public with a free training video series",
    "power bi": "Microsoft Learn's Power BI learning path",
    "docker": "the Docker 'Get Started' guide: containerize a small app you've written",
    "kubernetes": "the Kubernetes Basics tutorial on kubernetes.io with minikube or kind",
    "aws": "AWS Skill Builder's free Cloud Practitioner Essentials",
    "javascript": "javascript.info, first two parts",
    "typescript": "the TypeScript Handbook on typescriptlang.org",
    "react": "the official react.dev 'Learn' track",
    "machine learning": "the scikit-learn tutorials and one Kaggle 'Getting Started' "
                        "competition",
    "spark": "the PySpark quickstart on a local install",
    "git": "the Pro Git book (git-scm.com), chapters 1-3",
    "ci/cd": "GitHub Actions docs: add a test workflow to one of your repos",
    "rest api": "the FastAPI tutorial: build a small API with 3 endpoints",
    "excel": "Microsoft's Excel training: pivot tables, XLOOKUP, and charts",
}
DEFAULT_RESOURCE = "the official documentation's getting-started guide, plus one hands-on " \
                   "exercise you can show"


def _learnable(item: GapItem) -> bool:
    return (item.status != GapStatus.EVIDENCED
            and bool(item.missing_keywords)
            and (item.question is None or item.question.answer_kind != AnswerKind.CONFIRMED))


def _rank(item: GapItem) -> tuple:
    return (item.priority != Priority.REQUIRED, item.status != GapStatus.MISSING)


def pick_focus(analysis: GapAnalysis) -> tuple[list[str], dict[str, list[str]]]:
    """Up to MAX_FOCUS skills, and which requirement ids each one serves."""
    focus: list[str] = []
    serves: dict[str, list[str]] = {}
    for item in sorted(filter(_learnable, analysis.items), key=_rank):
        # "dbt or Airflow": learning one is enough.
        any_of = re.search(r"\bor\b", item.requirement_text, re.I)
        candidates = item.missing_keywords[:1] if any_of else item.missing_keywords
        if any_of and any(k in focus for k in item.missing_keywords):
            candidates = []
        for kw in candidates:
            if kw not in focus and len(focus) < MAX_FOCUS:
                focus.append(kw)
            if kw in focus:
                serves.setdefault(kw, []).append(item.requirement_id)
    return focus, serves


def _not_addressable(analysis: GapAnalysis) -> list[str]:
    out = []
    for item in analysis.items:
        if item.status == GapStatus.EVIDENCED:
            continue
        if item.question and item.question.answer_kind == AnswerKind.CONFIRMED:
            continue
        if "years" in item.rationale.lower() and "asks for" in item.rationale.lower():
            out.append(f"Years of experience ({item.requirement_text}): only time closes "
                       f"this. Show depth in what you have instead.")
        elif item.category == RequirementCategory.EDUCATION:
            out.append(f"Degree ({item.requirement_text}): some employers accept equivalent "
                       f"experience. Ask the recruiter.")
        elif item.category == RequirementCategory.CERTIFICATION:
            out.append(f"Certification ({item.requirement_text}): you can start it now, but "
                       f"list it only once earned (or as 'in progress' with a date).")
    return out


def build_plan(analysis: GapAnalysis) -> UpskillingPlan:
    focus, serves = pick_focus(analysis)
    strengths = [k for i in analysis.items if i.status == GapStatus.EVIDENCED
                 for k in i.matched_keywords][:2]
    base = f" with your existing {display_list(strengths)}" if strengths else ""

    def reqs(*skills):
        return sorted({r for s in skills for r in serves.get(s, [])})

    w1: list[PlanTask] = []
    if focus:
        first = focus[0]
        w1.append(PlanTask(
            id="w1t1", days="Days 1-2", title=f"Learn {display_name(first)} fundamentals",
            detail=f"Work through {RESOURCES.get(first, DEFAULT_RESOURCE)}.",
            deliverable=f"A small working {display_name(first)} exercise saved in a public repo or notebook.",
            requirement_ids=reqs(first)))
        second = focus[1] if len(focus) > 1 else first
        w1.append(PlanTask(
            id="w1t2", days="Days 3-4",
            title=(f"Learn {display_name(second)} fundamentals" if second != first
                   else f"Go deeper on {display_name(first)}"),
            detail=(f"Work through {RESOURCES.get(second, DEFAULT_RESOURCE)}."
                    if second != first else
                    f"Redo one task from your current job using {display_name(first)}, end to "
                    f"end."),
            deliverable="A second exercise, committed with a short README.",
            requirement_ids=reqs(second)))
        third = focus[2] if len(focus) > 2 else None
        w1.append(PlanTask(
            id="w1t3", days="Day 5",
            title=f"Intro to {display_name(third)}" if third else "Review and fill holes",
            detail=(f"Get a first hands-on look via {RESOURCES.get(third, DEFAULT_RESOURCE)}."
                    if third else
                    "Revisit the parts of week 1 that didn't stick; write down open questions."),
            deliverable="Notes on what you can now do, and what you can't yet.",
            requirement_ids=reqs(third) if third else []))
        week1_focus = f"Fundamentals: {display_list(focus)}"
    else:
        w1.append(PlanTask(
            id="w1t1", days="Days 1-3", title="Find your real numbers",
            detail="Go through each bullet without a metric. Check dashboards, tickets, old "
                   "emails, or ask a former manager for actual figures.",
            deliverable="A list of metrics you can verify, one per bullet where possible."))
        w1.append(PlanTask(
            id="w1t2", days="Days 4-5", title="Write your stories",
            detail="Write a STAR story (situation, task, action, result) for your three "
                   "strongest bullets.",
            deliverable="Three written stories, each under 200 words."))
        week1_focus = "Evidence: metrics and stories"

    w2: list[PlanTask] = []
    if focus:
        w2.append(PlanTask(
            id="w2t1", days="Days 6-8", title="Build one small, real project",
            detail=f"Combine {display_list(focus)}{base} on a public dataset close to this "
                   f"job's domain. Keep it small enough to finish.",
            deliverable="A repo with a README: the problem, what you built, and what you'd do "
                        "next.",
            requirement_ids=reqs(*focus)))
        w2.append(PlanTask(
            id="w2t2", days="Day 9", title="Add it to your resume, honestly",
            detail="Add the project under Projects, describing exactly what you built. It's a "
                   "personal project, not work experience, and the resume should say so.",
            deliverable="A Projects entry with 2-3 bullets, each one true."))
    w2.append(PlanTask(
        id="w2t3" if focus else "w2t1", days="Day 10" if focus else "Days 6-10",
        title="Prepare for the gap questions",
        detail="For each gap you still have, prepare a 30-second honest answer: what you know, "
               "what you've done about it, and how you'd ramp up.",
        deliverable="Written answers you've said out loud at least twice."))

    return UpskillingPlan(
        focus_skills=focus,
        weeks=[PlanWeek(week=1, focus=week1_focus, tasks=w1),
               PlanWeek(week=2, focus="Proof: build, document, prepare" if focus else
                        "Interview readiness", tasks=w2)],
        not_addressable=_not_addressable(analysis),
    )
