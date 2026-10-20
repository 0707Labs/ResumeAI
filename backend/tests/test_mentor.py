from datetime import date

import pytest

from app.analysis import analyze, apply_answers
from app.llm.client import LLMError
from app.mentor import build_advice, polish
from app.mentor.polish import _Items, acceptable
from app.models import ActionKind, Decision, GapSeverity
from app.parsing import parse_jd, parse_resume_text
from app.scoring import score
from tests.conftest import fixture_text

TODAY = date(2026, 10, 1)


def advise(resume_text, jd_text, answers=None):
    r, jd = parse_resume_text(resume_text), parse_jd(jd_text)
    g = analyze(r, jd, today=TODAY)
    if answers:
        g = apply_answers(g, answers(g))
    return r, g, build_advice(r, jd, g, score(r, jd, today=TODAY), today=TODAY)


STRONG = """Ira Sen
ira@example.com
Experience
Senior Data Analyst | Northwind | Jan 2018 – Present
• Wrote SQL and Python jobs that cut reporting time by 40%
• Built Tableau dashboards used by 300 sales reps
• Ran 25 A/B tests with statistics reviews for the growth team
• Moved 60 dbt models into Snowflake, saving $50k a year
Education
B.Sc. Statistics, Delhi University, 2017
Skills
SQL, Python, Tableau, dbt, Snowflake
"""

JD = """Senior Data Analyst
Requirements
- 5+ years with SQL and Python
- Tableau dashboards
- Statistics and A/B testing
Nice to have
- dbt or Airflow
- Snowflake
"""

JUNIOR = """Kai Wong
kai@example.com
Experience
Junior Analyst | Initech | Jan 2025 – Present
• Helped clean survey data in Excel
• Contributed to a weekly SQL report
Education
B.A. Economics, City College, 2024
"""


# --- verdict ----------------------------------------------------------------------------


def test_strong_fit():
    _, _, adv = advise(STRONG, JD)
    assert adv.verdict.decision == Decision.STRONG_FIT
    assert not [g for g in adv.gaps if g.severity == GapSeverity.CRITICAL]


def test_fixture_is_apply():
    _, _, adv = advise(fixture_text("resume_analyst.txt"), fixture_text("jd_senior_analyst.txt"))
    assert adv.verdict.decision == Decision.APPLY
    assert any("90%" in r for r in adv.verdict.reasons)
    assert "not a prediction" in adv.verdict.caveat


def test_junior_vs_senior_is_not_yet():
    _, _, adv = advise(JUNIOR, JD)
    assert adv.verdict.decision == Decision.NOT_YET
    assert any("level(s) below" in r for r in adv.verdict.reasons)


def test_stretch():
    mid = JUNIOR.replace("Jan 2025", "Jan 2022").replace(
        "• Contributed to a weekly SQL report",
        "• Contributed to a weekly SQL report\n• Built Tableau dashboards in Python")
    _, _, adv = advise(mid, JD)
    assert adv.verdict.decision == Decision.STRETCH


# --- strengths ------------------------------------------------------------------------------


def test_strengths_cite_real_bullets():
    r, _, adv = advise(fixture_text("resume_analyst.txt"), fixture_text("jd_senior_analyst.txt"))
    assert adv.strengths
    for s in adv.strengths:
        for bid in s.evidence_bullet_ids:
            assert r.bullet_by_id(bid) is not None
            assert r.bullet_by_id(bid).text in s.text or len(s.evidence_bullet_ids) > 1
    assert any(s.text.startswith("SQL, Python, and pandas") for s in adv.strengths)


# --- gaps -----------------------------------------------------------------------------------


def test_gap_severity_ordering():
    _, _, adv = advise(JUNIOR, JD)
    sev = [g.severity for g in adv.gaps]
    order = [GapSeverity.CRITICAL, GapSeverity.MODERATE, GapSeverity.MINOR]
    assert sev == sorted(sev, key=order.index)
    by_text = {g.text: g for g in adv.gaps}
    assert by_text["Tableau"].severity == GapSeverity.CRITICAL
    assert by_text["dbt or Airflow"].severity == GapSeverity.MINOR  # preferred, any-of wording


def test_confirmed_answer_downgrades_gap():
    def ans(g):
        q = next(i.question for i in g.items if "tableau" in i.missing_keywords)
        return {q.id: "Yes, I built two Tableau dashboards for the survey team."}
    _, _, adv = advise(JUNIOR, JD, ans)
    tab = next(g for g in adv.gaps if g.text == "Tableau")
    assert tab.severity == GapSeverity.MINOR and "cites your answer" in tab.why_it_matters
    assert any(a.kind == ActionKind.RESUME_EDIT and "Re-run tailoring" in a.text
               for a in adv.actions)


def test_declined_required_stays_critical_with_honest_framing():
    def ans(g):
        q = next(i.question for i in g.items if "tableau" in i.missing_keywords)
        return {q.id: "No, I haven't used it."}
    _, _, adv = advise(JUNIOR, JD, ans)
    tab = next(g for g in adv.gaps if g.text == "Tableau")
    assert tab.severity == GapSeverity.CRITICAL and "honestly" in tab.why_it_matters


def test_resume_level_gaps():
    _, _, adv = advise(JUNIOR, JD)
    assert any(g.requirement_id is None and "measurable" in g.text for g in adv.gaps)


# --- actions --------------------------------------------------------------------------------


def test_actions_start_with_open_questions_on_required_items():
    _, g, adv = advise(JUNIOR, JD)
    first = adv.actions[0]
    assert first.kind == ActionKind.ANSWER_QUESTION and first.question_id
    item = next(i for i in g.items if i.question and i.question.id == first.question_id)
    assert item.priority.value == "required"
    assert [a.id for a in adv.actions] == [f"a{i}" for i in range(1, len(adv.actions) + 1)]


def test_metric_actions_never_suggest_a_number():
    _, _, adv = advise(JUNIOR, JD)
    metric = [a for a in adv.actions if a.bullet_ids]
    assert metric and all("Don't estimate" in a.text for a in metric)


def test_not_yet_suggests_referral_strategy():
    _, _, adv = advise(JUNIOR, JD)
    assert any(a.kind == ActionKind.APPLY_STRATEGY and "referral" in a.text
               for a in adv.actions)


# --- plan -------------------------------------------------------------------------------------


def test_plan_is_two_weeks_of_ten_days():
    _, _, adv = advise(JUNIOR, JD)
    plan = adv.plan
    assert [w.week for w in plan.weeks] == [1, 2]
    days = " ".join(t.days for w in plan.weeks for t in w.tasks)
    for d in ("Days 1-2", "Days 3-4", "Day 5", "Days 6-8", "Day 9", "Day 10"):
        assert d in days


def test_plan_focus_required_first_and_any_of_picks_one():
    _, _, adv = advise(JUNIOR, JD)
    focus = adv.plan.focus_skills
    assert len(focus) <= 3
    assert focus[0] in {"python", "tableau", "statistics", "a/b testing"}
    assert not {"dbt", "airflow"} <= set(focus)


def test_plan_project_is_added_honestly():
    _, _, adv = advise(JUNIOR, JD)
    tasks = {t.title: t for w in adv.plan.weeks for t in w.tasks}
    honest = tasks["Add it to your resume, honestly"]
    assert "personal project, not work experience" in honest.detail


def test_plan_skips_skills_the_candidate_confirmed():
    def ans(g):
        q = next(i.question for i in g.items if "tableau" in i.missing_keywords)
        return {q.id: "Yes, two Tableau dashboards."}
    _, _, adv = advise(JUNIOR, JD, ans)
    assert "tableau" not in adv.plan.focus_skills


def test_years_gap_is_not_addressable():
    _, _, adv = advise(JUNIOR, JD)
    assert any("only time closes this" in n for n in adv.plan.not_addressable)


def test_no_learnable_gaps_gives_evidence_plan():
    _, _, adv = advise(STRONG, JD)
    assert adv.plan.focus_skills == []
    assert adv.plan.weeks[0].focus == "Evidence: metrics and stories"


# --- polish guards ----------------------------------------------------------------------------


@pytest.mark.parametrize("old, new, ok", [
    ("Answer question q1 about Tableau.", "Take a minute to answer q1 about Tableau.", True),
    ("Answer question q1 about Tableau.", "Answer q1 about Tableau and Power BI.", False),
    ("Add a real metric if you have one.", "Add a metric like 30% if you have one.", False),
    ('Shown directly in "Cut weekly reporting time by 30%".',
     'Your line "Cut weekly reporting time by 30%" proves it.', True),
    ('Shown directly in "Cut weekly reporting time by 30%".',
     'Your line "Cut reporting time a lot" proves it.', False),
    ("Short.", "x" * 200, False),
])
def test_polish_acceptance(old, new, ok):
    assert acceptable(old, new) is ok


class PolishLLM:
    def __init__(self, fn=None, error=None):
        self.fn, self.error = fn, error

    def parse(self, *, system, user, schema, effort="medium"):
        import json
        import re
        if self.error:
            raise self.error
        assert schema is _Items
        fields = json.loads(re.search(r"<texts>\n(.*)\n</texts>", user, re.S).group(1))
        return schema.model_validate({"items": [{"key": k, "text": self.fn(k, v)}
                                                for k, v in fields.items()]})


def test_polish_keeps_structure_and_verdict():
    _, _, adv = advise(JUNIOR, JD)

    def rewrite(key, text):
        if key == "verdict.headline":
            return "Apply now, you're a great fit!"  # tone only; decision can't move
        if key.startswith("actions."):
            return text + " Also learn Kubernetes."  # adds a skill: rejected
        return "Honestly: " + text

    out = polish(adv, PolishLLM(rewrite))
    assert out.verdict.decision == adv.verdict.decision == Decision.NOT_YET
    assert [a.text for a in out.actions] == [a.text for a in adv.actions]
    assert out.strengths and out.strengths[0].text.startswith("Honestly: ")
    assert [g.severity for g in out.gaps] == [g.severity for g in adv.gaps]
    assert any("discarded" in n for n in out.notes)


def test_polish_failure_keeps_rules_text():
    _, _, adv = advise(JUNIOR, JD)
    out = polish(adv, PolishLLM(error=LLMError("Claude declined this request.")))
    assert out.actions == adv.actions
    assert out.notes[-1] == "Kept rules wording: Claude declined this request."
