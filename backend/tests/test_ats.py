from datetime import date

import pytest

from app.analysis import analyze, apply_answers
from app.llm.client import LLMError
from app.models import WEIGHTS, Component, Seniority
from app.parsing import parse_jd, parse_resume_file, parse_resume_text
from app.parsing.synonyms import same_skill, skill_synonyms
from app.scoring import score, title_similarity
from app.scoring.semantic import _Lines
from app.tailoring import apply_tailoring, tailor
from tests.conftest import fixture_text
from tests.test_tailor import JD, ScriptedLLM, b
from tests.test_verifier import RESUME

TODAY = date(2026, 10, 1)


def comp(report, name):
    return next(c for c in report.components if c.name == name)


@pytest.fixture
def report():
    r = parse_resume_text(fixture_text("resume_analyst.txt"))
    jd = parse_jd(fixture_text("jd_senior_analyst.txt"))
    return score(r, jd, today=TODAY)


# --- report shape ------------------------------------------------------------------------


def test_breakdown_and_total(report):
    assert {c.name for c in report.components} == set(WEIGHTS)
    assert report.total == pytest.approx(sum(c.points for c in report.components), abs=0.2)
    assert "estimate" in report.disclaimer.lower()


def test_deterministic_without_llm():
    r = parse_resume_text(fixture_text("resume_analyst.txt"))
    jd = parse_jd(fixture_text("jd_senior_analyst.txt"))
    a, b_ = score(r, jd, today=TODAY), score(r, jd, today=TODAY)
    assert a == b_
    assert all(c.deterministic for c in a.components)


def test_fixture_breakdown(report):
    req = comp(report, Component.REQUIRED_KEYWORDS)
    assert req.missing == ["statistics"]
    assert "implied by a/b testing" in req.notes
    assert req.score == pytest.approx(6 / 7, abs=1e-3)
    pref = comp(report, Component.PREFERRED_KEYWORDS)
    assert pref.score == 0.0 and "dbt / airflow" in pref.missing  # any-of shown as one unit
    assert comp(report, Component.TITLE_SENIORITY).score == 1.0
    assert comp(report, Component.FORMAT_PARSEABILITY).score == 1.0
    impact = comp(report, Component.QUANTIFIED_IMPACT)
    assert impact.matched == ["exp1.b2", "exp2.b2"]


# --- synonym map ------------------------------------------------------------------------------


@pytest.mark.parametrize("a, b2", [("JS", "JavaScript"), ("k8s", "Kubernetes"),
                                   ("Postgres", "PostgreSQL"), ("golang", "Go"),
                                   ("sklearn", "scikit-learn"), ("PowerBI", "Power BI")])
def test_same_skill(a, b2):
    assert same_skill(a, b2)


def test_different_skills_are_different():
    assert not same_skill("Java", "JavaScript")
    assert not same_skill("React", "Reactive")


def test_synonym_map_is_exposed():
    syn = skill_synonyms()
    assert "js" in syn["javascript"]  # matched case-insensitively
    assert "Go" in syn["go"]  # English-word aliases keep their required casing


def test_alias_in_resume_matches_jd_keyword():
    r = parse_resume_text("A B\na@b.co\nExperience\nDev | X Corp | 2020 - Present\n"
                          "• Built charts in JS on k8s")
    jd = parse_jd("Engineer\nRequirements\n- JavaScript\n- Kubernetes")
    req = comp(score(r, jd, today=TODAY), Component.REQUIRED_KEYWORDS)
    assert req.score == 1.0 and req.matched == ["javascript", "kubernetes"]


def test_skills_only_keyword_noted():
    r = parse_resume_text("A B\na@b.co\nExperience\nDev | X Corp | 2020 - Present\n"
                          "• Built charts\nSkills\nTableau")
    jd = parse_jd("Analyst\nRequirements\n- Tableau")
    req = comp(score(r, jd, today=TODAY), Component.REQUIRED_KEYWORDS)
    assert req.score == 1.0 and "Only in your Skills list" in req.notes


# --- title / seniority ---------------------------------------------------------------------------


@pytest.mark.parametrize("jd_title, cand, low, high", [
    ("Senior Data Analyst", "Data Analyst", 1.0, 1.0),
    ("Backend Engineer", "Backend Developer", 1.0, 1.0),  # engineer ~ developer
    ("Data Analyst", "Marketing Analyst", 0.6, 0.65),  # same role, different domain
    ("Data Engineer", "Data Analyst", 0.3, 0.3),  # same domain, different role
    ("Product Designer", "Data Analyst", 0.0, 0.0),
])
def test_title_similarity(jd_title, cand, low, high):
    assert low <= title_similarity(jd_title, cand) <= high


@pytest.mark.parametrize("years_line, expected", [
    ("Jan 2025 – Present", 0.5),   # ~1.8y -> junior vs senior: 2 below -> 0 seniority
    ("Jan 2023 – Present", 0.75),  # ~3.8y -> mid vs senior: 1 below -> 0.5
    ("Jan 2019 – Present", 1.0),   # ~7.8y -> senior
])
def test_seniority_gap(years_line, expected):
    r = parse_resume_text(f"A B\na@b.co\nExperience\nData Analyst | X Corp | {years_line}\n"
                          f"• Did things")
    jd = parse_jd("Senior Data Analyst\nRequirements\n- SQL")
    assert jd.seniority == Seniority.SENIOR
    assert comp(score(r, jd, today=TODAY), Component.TITLE_SENIORITY).score == expected


# --- format ---------------------------------------------------------------------------------------


def test_format_deductions():
    r = parse_resume_text("just a paragraph with no structure")
    f = comp(score(r, parse_jd("Analyst\nRequirements\n- SQL"), today=TODAY),
             Component.FORMAT_PARSEABILITY)
    assert f.score < 0.3
    assert any("Education" in m for m in f.missing)


def test_two_column_pdf_scores_lower_on_format(two_column_pdf, analyst_pdf):
    jd = parse_jd("Engineer\nRequirements\n- Java")
    two = comp(score(parse_resume_file(two_column_pdf, "a.pdf"), jd, today=TODAY),
               Component.FORMAT_PARSEABILITY)
    one = comp(score(parse_resume_file(analyst_pdf, "a.pdf"), jd, today=TODAY),
               Component.FORMAT_PARSEABILITY)
    assert two.score < one.score
    assert any("multi-column" in m for m in two.missing)


# --- impact ------------------------------------------------------------------------------------------


def test_years_are_not_metrics():
    r = parse_resume_text("A B\na@b.co\nExperience\nDev | X | 2020 - 2021\n"
                          "• Joined in 2020 and shipped the app\n• Cut costs by 10%")
    c = comp(score(r, parse_jd("Dev\nRequirements\n- SQL"), today=TODAY),
             Component.QUANTIFIED_IMPACT)
    assert c.matched == ["exp1.b2"] and c.score == 1.0  # 1 of 2 = 50% = target


# --- semantic ------------------------------------------------------------------------------------------


def test_semantic_rules_breakdown(report):
    s = comp(report, Component.SEMANTIC_RELEVANCE)
    assert "Partner with product and engineering on experiment design" in s.matched
    assert "Bachelor's degree in a quantitative field" in s.matched  # via degree check
    assert "Mentor junior analysts" in s.missing  # being a junior isn't mentoring one


class SemanticLLM:
    def __init__(self, lines=None, error=None):
        self.lines, self.error = lines or [], error

    def parse(self, *, system, user, schema, effort="medium"):
        if self.error:
            raise self.error
        assert schema is _Lines
        return schema.model_validate({"lines": self.lines})


def test_semantic_llm_needs_citations():
    r = parse_resume_text(fixture_text("resume_analyst.txt"))
    jd = parse_jd(fixture_text("jd_senior_analyst.txt"))
    rules = comp(score(r, jd, today=TODAY), Component.SEMANTIC_RELEVANCE)
    llm = SemanticLLM([
        {"line_id": 2, "score": 1.0, "bullet_ids": ["exp9.b9"]},  # bogus citation: ignored
        {"line_id": 99, "score": 1.0, "bullet_ids": ["exp1.b1"]},  # bogus line: ignored
        {"line_id": 0, "score": 0.0, "bullet_ids": []},  # zero needs no citation
    ])
    s = comp(score(r, jd, llm=llm, today=TODAY), Component.SEMANTIC_RELEVANCE)
    assert s.deterministic is False and "Judged by Claude for 1 of" in s.notes
    assert s.score < rules.score  # line 0 dropped to 0; nothing else changed


def test_semantic_llm_failure_falls_back():
    r = parse_resume_text(fixture_text("resume_analyst.txt"))
    jd = parse_jd(fixture_text("jd_senior_analyst.txt"))
    s = comp(score(r, jd, llm=SemanticLLM(error=LLMError("down")), today=TODAY),
             Component.SEMANTIC_RELEVANCE)
    assert s.deterministic and "Claude unavailable: down" in s.notes


# --- before / after ------------------------------------------------------------------------------------


def test_verified_tailoring_can_raise_score_but_fabrication_cannot():
    resume, jd = parse_resume_text(RESUME), parse_jd(JD)
    analysis = analyze(resume, jd)
    qid = next(i.question.id for i in analysis.items
               if i.question and "airflow" in i.missing_keywords)
    analysis = apply_answers(analysis, {qid: "Yes, I wrote the Airflow DAGs for the SQL "
                                             "extracts at Acme."})
    before = score(resume, jd, today=TODAY)

    honest = tailor(resume, jd, analysis, llm=ScriptedLLM({"bullets": [
        b(["exp1.b2"], "Cut weekly reporting time by 30% by automating SQL extracts as "
          "Airflow DAGs", answers=[qid])]}))
    after = score(apply_tailoring(resume, honest), jd, today=TODAY)
    assert comp(after, Component.REQUIRED_KEYWORDS).score > \
        comp(before, Component.REQUIRED_KEYWORDS).score
    assert after.total > before.total

    # A fabricated Snowflake/Python bullet is blocked, reverted, and earns nothing.
    faked = tailor(resume, jd, analysis, llm=ScriptedLLM(
        {"bullets": [b(["exp1.b2"], "Cut weekly reporting time by 30% with Python on "
                     "Snowflake")]},
        {"bullets": [b(["exp1.b2"], "Cut reporting time by 30% using Python and Snowflake")]}))
    faked_after = score(apply_tailoring(resume, faked), jd, today=TODAY)
    assert faked_after.total == before.total
