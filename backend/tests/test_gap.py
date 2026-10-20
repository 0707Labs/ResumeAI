from datetime import date

import pytest

from app.analysis import AnswerError, analyze, apply_answers, refine_with_llm
from app.analysis.experience import parse_month, years_of_experience
from app.llm.client import LLMError
from app.models import (
    AnswerKind,
    GapStatus,
    JobDescription,
    Priority,
    Requirement,
    RequirementCategory,
)
from app.parsing import parse_jd, parse_resume_text
from tests.conftest import fixture_text

TODAY = date(2026, 10, 1)


def req(text, *, id="req1", priority=Priority.REQUIRED, category=None, keywords=None):
    """Build a Requirement the way the JD parser would (keywords from the lexicon)."""
    from app.parsing.lexicon import find_skills

    kws = find_skills(text) if keywords is None else keywords
    if category is None:
        category = RequirementCategory.SKILL if kws else RequirementCategory.OTHER
    return Requirement(id=id, text=text, priority=priority, category=category, keywords=kws)


def jd_of(*reqs) -> JobDescription:
    return JobDescription(title="Analyst", requirements=list(reqs))


RESUME = """Dev Patel
dev@example.com
Experience
Data Analyst | Lumen Health | Jan 2023 – Present
• Built cohort retention reports in SQL for the care team
• Cleaned claims data with pandas
• Mentored two new analysts on our reporting stack
Analytics Intern | Lumen Health | Jun 2022 – Dec 2022
• Wrote Excel macros for the finance team
Education
B.Sc. Statistics, Pune University, 2022
Certifications
AWS Certified Cloud Practitioner (2023)
Skills
SQL, Python, Tableau, Excel
"""


@pytest.fixture
def resume():
    return parse_resume_text(RESUME)


def one(resume, *reqs):
    return analyze(resume, jd_of(*reqs), today=TODAY).items


# --- keyword requirements -------------------------------------------------------------


def test_skill_named_in_bullet_is_evidenced(resume):
    [item] = one(resume, req("Strong SQL"))
    assert item.status == GapStatus.EVIDENCED
    assert item.evidence_bullet_ids == ["exp1.b1"]
    assert item.question is None


def test_skill_only_in_skills_list_is_evidenced_but_asks_for_example(resume):
    [item] = one(resume, req("Tableau dashboards"))
    assert item.status == GapStatus.EVIDENCED
    assert item.evidence_bullet_ids == [] and item.evidence_skills == ["tableau"]
    assert "no bullet shows it in use" in item.question.question


def test_related_tool_only_implies_never_evidences(resume):
    # pandas implies Python, but this resume has "Python" in Skills -> evidenced.
    # Remove it and the pandas bullet alone must only imply Python.
    r = parse_resume_text(RESUME.replace("SQL, Python, Tableau", "SQL, Tableau"))
    [item] = one(r, req("Python for analysis"))
    assert item.status == GapStatus.IMPLIED
    assert item.evidence_bullet_ids == ["exp1.b2"]
    assert item.missing_keywords == ["python"]
    assert "pandas" in item.rationale
    assert "Did you use Python directly?" in item.question.question


def test_job_title_implies_skill(resume):
    r = parse_resume_text(RESUME.replace("SQL, Python, Tableau, Excel", "Excel"))
    [item] = one(r, req("Background in data analysis"))
    assert item.status == GapStatus.IMPLIED
    assert item.evidence_entry_ids == ["exp1"]


def test_all_of_requires_every_keyword(resume):
    [item] = one(resume, req("SQL and Airflow"))
    assert item.status == GapStatus.IMPLIED  # partial: SQL yes, Airflow no
    assert item.matched_keywords == ["sql"] and item.missing_keywords == ["airflow"]
    assert "not found: Airflow" in item.rationale


def test_any_of_needs_one_keyword(resume):
    [item] = one(resume, req("Tableau or Power BI"))
    assert item.status == GapStatus.EVIDENCED


def test_slash_inside_a_skill_is_not_an_or(resume):
    [item] = one(resume, req("SQL and A/B testing"))
    assert item.status != GapStatus.EVIDENCED
    assert "a/b testing" in item.missing_keywords


def test_absent_skill_is_missing_with_neutral_question(resume):
    [item] = one(resume, req("Kubernetes in production"))
    assert item.status == GapStatus.MISSING
    assert item.evidence_bullet_ids == [] and item.question is not None
    q = item.question.question
    assert "Kubernetes" in q and "If not, just say no" in q


# --- years ------------------------------------------------------------------------------


def test_years_from_dates_merge_overlaps_and_skip_internships(resume):
    assert years_of_experience(resume, today=TODAY) == pytest.approx(3.8)  # Jan 2023–Oct 2026


def test_not_enough_years_downgrades_evidenced_skill(resume):
    [item] = one(resume, req("5+ years of SQL"))
    assert item.status == GapStatus.IMPLIED
    assert "Asks for 5+ years" in item.rationale


def test_enough_years_keeps_evidenced(resume):
    [item] = one(resume, req("3+ years of SQL"))
    assert item.status == GapStatus.EVIDENCED


def test_years_only_requirement(resume):
    [item] = one(resume, req("7+ years of professional experience",
                             category=RequirementCategory.EXPERIENCE, keywords=[]))
    assert item.status == GapStatus.MISSING
    assert "freelance" in item.question.question


@pytest.mark.parametrize("text, is_end, expected", [
    ("Jan 2023", False, 2023 * 12),
    ("Sept 2021", False, 2021 * 12 + 8),
    ("03/2020", False, 2020 * 12 + 2),
    ("2019", False, 2019 * 12),
    ("2019", True, 2019 * 12 + 11),
    ("Present", True, 2026 * 12 + 9),
    ("sometime", True, None),
])
def test_parse_month(text, is_end, expected):
    assert parse_month(text, is_end=is_end, today=TODAY) == expected


# --- education / certification -------------------------------------------------------


def test_degree_meets_level(resume):
    [item] = one(resume, req("Bachelor's degree in a quantitative field",
                             category=RequirementCategory.EDUCATION, keywords=[]))
    assert item.status == GapStatus.EVIDENCED and item.evidence_entry_ids == ["edu1"]


def test_degree_below_level(resume):
    [item] = one(resume, req("Master's degree in Statistics",
                             category=RequirementCategory.EDUCATION, keywords=[]))
    assert item.status == GapStatus.MISSING
    assert "master's" in item.rationale and "bachelor's" in item.rationale


def test_certification_match(resume):
    [item] = one(resume, req("AWS Certified Cloud Practitioner",
                             category=RequirementCategory.CERTIFICATION, keywords=[]))
    assert item.status == GapStatus.EVIDENCED and item.evidence_bullet_ids == ["cert1.b1"]


def test_certification_mismatch(resume):
    [item] = one(resume, req("PMP certification",
                             category=RequirementCategory.CERTIFICATION, keywords=[]))
    assert item.status == GapStatus.MISSING


# --- requirements without keywords ---------------------------------------------------


def test_word_overlap_only_implies(resume):
    [item] = one(resume, req("Mentor new analysts"))
    assert item.status == GapStatus.IMPLIED
    assert item.evidence_bullet_ids == ["exp1.b3"]
    assert item.decided_by == "rules-fuzzy"


def test_no_overlap_is_missing(resume):
    [item] = one(resume, req("Comfortable presenting to executives"))
    assert item.status == GapStatus.MISSING


# --- whole pipeline on fixtures ----------------------------------------------------------


def test_fixture_pipeline():
    r = parse_resume_text(fixture_text("resume_analyst.txt"))
    jd = parse_jd(fixture_text("jd_senior_analyst.txt"))
    g = analyze(r, jd, today=TODAY)
    status = {i.requirement_id: i.status for i in g.items}
    assert status == {
        "req1": GapStatus.EVIDENCED,  # data analysis + 6.4 years
        "req2": GapStatus.EVIDENCED,  # SQL, Python, pandas
        "req3": GapStatus.EVIDENCED,  # Tableau (any-of with Power BI)
        "req4": GapStatus.IMPLIED,  # A/B test shown, statistics only implied
        "req5": GapStatus.MISSING,  # dbt / Airflow
        "req6": GapStatus.EVIDENCED,  # B.Tech
        "req7": GapStatus.MISSING,  # Snowflake / BigQuery
        "req8": GapStatus.MISSING,  # JS
    }
    # Every non-evidenced item has a question; ids are sequential.
    qs = g.questions()
    assert [q.id for q in qs] == [f"q{i}" for i in range(1, len(qs) + 1)]
    assert all(i.question for i in g.items if i.status != GapStatus.EVIDENCED)
    assert g.counts == {"evidenced": 4, "implied": 1, "missing": 3}
    assert g.required_coverage == 0.9  # 5 required: 4 evidenced + 1 implied (half credit)


# --- answers --------------------------------------------------------------------------------


@pytest.fixture
def analysis(resume):
    return analyze(resume, jd_of(req("Airflow", id="req1"), req("Kubernetes", id="req2")),
                   today=TODAY)


def test_answers_are_recorded_without_changing_status(analysis):
    updated = apply_answers(analysis, {
        "q1": "Yes - I scheduled our SQL reports as Airflow DAGs at Lumen.",
        "q2": "No, never used it.",
    })
    q1, q2 = updated.questions()
    assert q1.answer_kind == AnswerKind.CONFIRMED
    assert q2.answer_kind == AnswerKind.DECLINED
    assert [i.status for i in updated.items] == [GapStatus.MISSING, GapStatus.MISSING]
    assert updated.confirmed_answers() == {
        "q1": "Yes - I scheduled our SQL reports as Airflow DAGs at Lumen."}


def test_blank_answer_stays_unanswered(analysis):
    updated = apply_answers(analysis, {"q1": "   "})
    assert updated.questions()[0].answer_kind == AnswerKind.UNANSWERED


def test_unknown_question_id_rejected(analysis):
    with pytest.raises(AnswerError, match="q9"):
        apply_answers(analysis, {"q9": "yes"})


def test_answer_kind_cannot_be_forged(analysis):
    dumped = analysis.model_dump()
    dumped["items"][0]["question"]["answer_kind"] = "confirmed"
    reloaded = type(analysis).model_validate(dumped)
    assert reloaded.questions()[0].answer_kind == AnswerKind.UNANSWERED


# --- LLM refinement guardrails ------------------------------------------------------------


class FakeLLM:
    def __init__(self, verdicts=None, error=None):
        self.verdicts, self.error, self.calls = verdicts or [], error, []

    def parse(self, *, system, user, schema, effort="medium"):
        self.calls.append(user)
        if self.error:
            raise self.error
        return schema.model_validate({"verdicts": self.verdicts})


def v(req_id, status, ids=(), q="Have you done this? If not, say no."):
    return {"requirement_id": req_id, "status": status, "evidence_bullet_ids": list(ids),
            "rationale": "because", "question": q}


@pytest.fixture
def mixed(resume):
    return analyze(resume, jd_of(
        req("Strong SQL", id="req1"),                               # evidenced by rules
        req("Experience with Airflow", id="req2"),                  # missing
        req("Comfortable presenting to executives", id="req3"),     # missing, no keywords
    ), today=TODAY)


def test_llm_only_sees_unsettled_items(mixed, resume):
    llm = FakeLLM([v("req2", "missing"), v("req3", "missing")])
    refine_with_llm(mixed, resume, llm)
    assert "req1" not in llm.calls[0] and "req2" in llm.calls[0] and "req3" in llm.calls[0]


def test_llm_can_imply_with_valid_citation(mixed, resume):
    llm = FakeLLM([v("req2", "implied", ["exp1.b1"], q="Did you orchestrate the SQL "
                   "reports with Airflow specifically? If not, say no.")])
    out, note = refine_with_llm(mixed, resume, llm)
    item = out.items[1]
    assert item.status == GapStatus.IMPLIED and item.decided_by == "llm"
    assert item.evidence_bullet_ids == ["exp1.b1"]
    assert item.missing_keywords == ["airflow"]  # still needs the candidate to confirm
    assert item.question.question.startswith("Did you orchestrate")
    assert "1 changed status" in note


def test_llm_citing_unknown_bullet_stays_missing(mixed, resume):
    out, _ = refine_with_llm(mixed, resume, FakeLLM([v("req2", "implied", ["exp9.b9"])]))
    assert out.items[1].status == GapStatus.MISSING
    assert out.items[1].evidence_bullet_ids == []


def test_llm_cannot_touch_rule_evidenced_items(mixed, resume):
    out, _ = refine_with_llm(mixed, resume, FakeLLM([v("req1", "missing")]))
    assert out.items[0].status == GapStatus.EVIDENCED and out.items[0].decided_by == "rules"


def test_llm_cannot_return_evidenced():
    from pydantic import ValidationError

    from app.analysis.refine import _Verdicts
    with pytest.raises(ValidationError):
        _Verdicts.model_validate({"verdicts": [v("req2", "evidenced", ["exp1.b1"])]})


def test_llm_failure_falls_back_to_rules(mixed, resume):
    out, note = refine_with_llm(mixed, resume, FakeLLM(error=LLMError("Claude declined.")))
    assert out == mixed
    assert note == "Used rules only: Claude declined."


def test_questions_renumbered_after_llm(mixed, resume):
    out, _ = refine_with_llm(mixed, resume, FakeLLM([v("req2", "missing"),
                                                    v("req3", "missing")]))
    assert [q.id for q in out.questions()] == ["q1", "q2"]


# --- explicit yes/no/skip from the UI ------------------------------------------------------------


def test_explicit_yes_wins_over_negative_wording(analysis):
    from app.models import AnswerIn

    updated = apply_answers(analysis, {
        "q1": AnswerIn(choice="yes", text="No formal training, but I run our Airflow DAGs."),
    })
    q = updated.questions()[0]
    assert q.answer_kind == AnswerKind.CONFIRMED and q.answer_choice == "yes"
    assert "q1" in updated.confirmed_answers()


def test_explicit_no_and_skip(analysis):
    from app.models import AnswerIn

    updated = apply_answers(analysis, {"q1": AnswerIn(choice="no"), "q2": AnswerIn(choice="skip")})
    q1, q2 = updated.questions()
    assert q1.answer_kind == AnswerKind.DECLINED and q1.answer == "No"
    assert q2.answer_kind == AnswerKind.UNANSWERED and q2.answer is None


def test_skip_clears_an_earlier_answer(analysis):
    from app.models import AnswerIn

    answered = apply_answers(analysis, {"q1": AnswerIn(choice="yes", text="Airflow at Lumen.")})
    skipped = apply_answers(answered, {"q1": AnswerIn(choice="skip")})
    assert skipped.questions()[0].answer_kind == AnswerKind.UNANSWERED
    assert skipped.confirmed_answers() == {}


def test_yes_needs_a_description(analysis):
    from app.models import AnswerIn

    with pytest.raises(AnswerError, match="describe"):
        apply_answers(analysis, {"q1": AnswerIn(choice="yes", text="   ")})


def test_answer_choice_cannot_be_forged_into_confirmed(analysis):
    dumped = analysis.model_dump()
    dumped["items"][0]["question"]["answer_choice"] = "yes"  # but no answer text
    reloaded = type(analysis).model_validate(dumped)
    assert reloaded.questions()[0].answer_kind == AnswerKind.UNANSWERED
