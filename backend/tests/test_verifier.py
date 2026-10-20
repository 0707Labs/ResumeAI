"""The anti-fabrication verifier.

Each case is a rewrite a tailoring model is tempted to make when a resume falls
short of a JD. Every fabrication must be BLOCKED; every honest rewrite must pass.
"""

import pytest

from app.analysis import analyze, apply_answers
from app.models import (
    ChangeType,
    FlagKind,
    JobDescription,
    Priority,
    Requirement,
    Severity,
    TailoredBullet,
)
from app.parsing import parse_resume_text
from app.tailoring.verifier import quantities, verify_bullet, verify_summary

# A junior-ish resume applied against a senior JD: lots of temptation.
RESUME = """Nina Kapoor
nina@example.com
Experience
Data Analyst | Acme Retail Pvt Ltd | Jan 2022 – Present
• Contributed to a churn dashboard in Tableau used by the customer success team
• Cut weekly reporting time by 30% by automating SQL extracts
• Partnered with product managers on A/B test readouts
• Helped migrate 14 legacy reports to Looker
• Cleaned order data with pandas, saving the team 6 hours a week
Junior Analyst | Brightline Logistics | Jun 2020 – Dec 2021
• Assisted senior analysts with shipment cost analysis in Excel
• Built 12 recurring reports for regional operations leads
• Reduced late-delivery escalations by 28% by flagging at-risk routes
Skills
SQL, Tableau, Excel, pandas
"""

JD_TEXT = ("Senior Data Analyst. Own the analytics roadmap. Lead stakeholder reviews. "
           "Python, Airflow, dbt, Snowflake. Partner with cross-functional teams to deliver "
           "data-driven insights for business stakeholders.")


@pytest.fixture(scope="module")
def resume():
    return parse_resume_text(RESUME)


def tb(text, *sources, answers=(), change=ChangeType.REWORD):
    return TailoredBullet(id="t1", text=text, source_bullet_ids=list(sources),
                          source_answer_ids=list(answers), change_type=change)


def blocks(result):
    return {(f.kind, f.token.lower()) for f in result.flags if f.severity == Severity.BLOCK}


def kinds(result):
    return {f.kind for f in result.flags if f.severity == Severity.BLOCK}


def check(resume, text, *sources, **kw):
    return verify_bullet(tb(text, *sources, **kw), resume, jd_text=JD_TEXT)


# --- sanity: the source bullets as written ---------------------------------------------


def test_fixture_ids(resume):
    assert resume.bullet_by_id("exp1.b1").text.startswith("Contributed to a churn dashboard")
    assert resume.bullet_by_id("exp2.b3").text.startswith("Reduced late-delivery")


def test_unchanged_bullets_always_pass(resume):
    for b in resume.bullets():
        r = verify_bullet(tb(b.text, b.id, change=ChangeType.UNCHANGED), resume, jd_text=JD_TEXT)
        assert r.passed and r.flags == [], (b.id, r.flags)


# --- honest rewrites pass -----------------------------------------------------------------


@pytest.mark.parametrize("text, sources", [
    # reword with synonyms, same strength
    ("Reduced weekly reporting time by 30% by automating SQL extracts", ["exp1.b2"]),
    ("Automated SQL extracts, cutting weekly reporting time by 30%", ["exp1.b2"]),
    # surface the existing metric first
    ("Saved the team 6 hours a week by cleaning order data with pandas", ["exp1.b5"]),
    # mirror JD wording ("stakeholders") without changing the fact
    ("Partnered with product managers and stakeholders on A/B test readouts", ["exp1.b3"]),
    # keep the support verb while mirroring "data-driven"
    ("Contributed to a data-driven churn dashboard in Tableau for the customer success team",
     ["exp1.b1"]),
    # merge two bullets from the same role
    ("Built 12 recurring reports for regional operations leads and reduced late-delivery "
     "escalations by 28%", ["exp2.b2", "exp2.b3"]),
])
def test_honest_rewrites_pass(resume, text, sources):
    r = check(resume, text, *sources)
    assert r.passed, r.flags


def test_alias_mirroring_passes(resume):
    # "PostgreSQL" vs "Postgres" is the same fact.
    r = parse_resume_text("A B\nExperience\nDev | Initech | 2020 - 2021\n• Tuned Postgres queries")
    out = verify_bullet(tb("Tuned PostgreSQL queries", "exp1.b1"), r)
    assert out.passed, out.flags


# --- tempted to add tools -----------------------------------------------------------------


@pytest.mark.parametrize("text, source, tool", [
    # JD wants Python; the source only names pandas (which implies, but doesn't state, it)
    ("Cleaned order data with Python and pandas, saving the team 6 hours a week",
     "exp1.b5", "python"),
    # JD wants Airflow
    ("Cut weekly reporting time by 30% by automating SQL extracts with Airflow",
     "exp1.b2", "airflow"),
    # JD wants Snowflake
    ("Cut weekly reporting time by 30% by automating Snowflake SQL extracts", "exp1.b2",
     "snowflake"),
    # Tool from a different bullet of the same resume
    ("Contributed to a churn dashboard in Tableau and Looker", "exp1.b1", "looker"),
    # Skills list mentions Excel, but this bullet's source doesn't
    ("Cleaned order data with pandas and Excel, saving the team 6 hours a week",
     "exp1.b5", "excel"),
])
def test_new_tools_blocked(resume, text, source, tool):
    r = check(resume, text, source)
    assert not r.passed
    assert (FlagKind.NEW_TOOL, tool) in blocks(r)


def test_unknown_acronym_blocked(resume):
    r = check(resume, "Cut weekly reporting time by 30% with an ETL framework in GCP Dataflow",
              "exp1.b2")
    assert FlagKind.NEW_TOOL in kinds(r)
    assert any(tok in {"gcp", "dataflow"} for _, tok in blocks(r))


# --- tempted to invent or inflate numbers -----------------------------------------------


@pytest.mark.parametrize("text, source, bad", [
    ("Cut weekly reporting time by 40% by automating SQL extracts", "exp1.b2", "40%"),
    # rounding up is still a new number
    ("Reduced late-delivery escalations by 30% by flagging at-risk routes", "exp2.b3", "30%"),
    # new metric attached to a bullet that had none
    ("Contributed to a churn dashboard in Tableau used by 50+ customer success managers",
     "exp1.b1", "50"),
    ("Contributed to a churn dashboard in Tableau that retained $2M in revenue",
     "exp1.b1", "$2m"),
    # "doubled" asserts a number too
    ("Doubled reporting speed by automating SQL extracts", "exp1.b2", "doubled"),
    # number in words
    ("Built twenty recurring reports for regional operations leads", "exp2.b2", "twenty"),
    # same digits, different kind: 30% is not 30 hours
    ("Cut weekly reporting time by 30 hours by automating SQL extracts", "exp1.b2", "30"),
])
def test_new_numbers_blocked(resume, text, source, bad):
    r = check(resume, text, source)
    assert (FlagKind.NEW_NUMBER, bad) in blocks(r), r.flags


def test_number_words_and_digits_are_equivalent(resume):
    r = check(resume, "Built twelve recurring reports for regional operations leads", "exp2.b2")
    assert FlagKind.NEW_NUMBER not in kinds(r)


@pytest.mark.parametrize("text, expected", [
    ("30%", [(30.0, "percent")]),
    ("$1.2M", [(1_200_000.0, "money")]),
    ("1,200 users", [(1200.0, "plain")]),
    ("3x faster", [(3.0, "multiple")]),
    ("p95 latency on S3", []),  # identifiers aren't quantities
    ("halved", [(0.5, "multiple"), (50.0, "percent")]),
])
def test_quantity_parsing(text, expected):
    assert [(q.value, q.kind) for q in quantities(text)] == expected


# --- tempted to inflate scope / verbs --------------------------------------------------------


@pytest.mark.parametrize("text, source, word", [
    ("Led a churn dashboard in Tableau used by the customer success team", "exp1.b1", "led"),
    ("Built a churn dashboard in Tableau used by the customer success team", "exp1.b1",
     "built"),
    ("Owned the churn dashboard in Tableau for the customer success team", "exp1.b1", "owned"),
    ("Migrated 14 legacy reports to Looker", "exp1.b4", "migrated"),
    ("Spearheaded shipment cost analysis in Excel", "exp2.b1", "spearheaded"),
    ("Analyzed shipment costs in Excel", "exp2.b1", "analyzed"),
    ("Led A/B test readouts with product managers", "exp1.b3", "led"),
    ("Built 12 recurring reports and led reviews with regional operations leads", "exp2.b2",
     "led"),
    ("Single-handedly built 12 recurring reports for regional operations leads", "exp2.b2",
     "single-handedly"),
    ("Built 12 recurring reports end-to-end for regional operations leads", "exp2.b2",
     "end-to-end"),
])
def test_inflation_blocked(resume, text, source, word):
    r = check(resume, text, source)
    assert (FlagKind.INFLATED_VERB, word) in blocks(r), r.flags


def test_operations_leads_noun_does_not_license_led(resume):
    # exp2.b2 mentions "operations leads" (people). That's not the candidate leading.
    r = check(resume, "Led 12 recurring reports for regional operations leads", "exp2.b2")
    assert FlagKind.INFLATED_VERB in kinds(r)


# --- tempted to add titles or seniority --------------------------------------------------------


@pytest.mark.parametrize("text, source, title", [
    ("As senior analyst, cut weekly reporting time by 30% by automating SQL extracts",
     "exp1.b2", "senior"),
    ("Partnered with product managers as team lead on A/B test readouts", "exp1.b3",
     "team lead"),
    ("Cut weekly reporting time by 30% as lead analyst by automating SQL extracts", "exp1.b2",
     "lead analyst"),
])
def test_new_titles_blocked(resume, text, source, title):
    assert (FlagKind.NEW_TITLE, title) in blocks(check(resume, text, source))


def test_title_already_in_source_is_fine(resume):
    # "senior analysts" and "product managers" are in the source bullets.
    assert check(resume, "Assisted senior analysts with shipment cost analysis in Excel",
                 "exp2.b1").passed
    assert FlagKind.NEW_TITLE not in kinds(
        check(resume, "Partnered with product managers on A/B test readouts", "exp1.b3"))


# --- tempted to move work between employers -------------------------------------------------


def test_other_employer_blocked(resume):
    r = check(resume, "Cut weekly reporting time by 30% at Brightline Logistics by automating "
                      "SQL extracts", "exp1.b2")
    assert (FlagKind.NEW_EMPLOYER, "brightline logistics") in blocks(r)


def test_own_employer_is_fine(resume):
    r = check(resume, "Cut Acme Retail's weekly reporting time by 30% by automating SQL "
                      "extracts", "exp1.b2")
    assert FlagKind.NEW_EMPLOYER not in kinds(r) and FlagKind.NEW_TOOL not in kinds(r)


def test_cross_entry_merge_blocked(resume):
    r = check(resume, "Cut reporting time by 30% and built 12 recurring reports",
              "exp1.b2", "exp2.b2")
    assert FlagKind.CROSS_ENTRY in kinds(r)


# --- sources (rule 4) ---------------------------------------------------------------------------


def test_missing_source_blocked(resume):
    r = verify_bullet(tb("Built dashboards"), resume)
    assert kinds(r) == {FlagKind.MISSING_SOURCE}


def test_unknown_source_blocked(resume):
    r = check(resume, "Built dashboards", "exp9.b1")
    assert FlagKind.UNKNOWN_SOURCE in kinds(r)


# --- candidate answers (rule 1) ----------------------------------------------------------------


@pytest.fixture
def answered(resume):
    jd = JobDescription(requirements=[
        Requirement(id="req1", text="Airflow", priority=Priority.REQUIRED, keywords=["airflow"]),
        Requirement(id="req2", text="dbt", priority=Priority.REQUIRED, keywords=["dbt"]),
    ])
    analysis = analyze(resume, jd)
    return apply_answers(analysis, {
        "q1": "Yes, the SQL extracts at Acme ran as Airflow DAGs that I wrote.",
        "q2": "No, haven't used dbt.",
    })


def test_confirmed_answer_licenses_the_tool(resume, answered):
    b = tb("Cut weekly reporting time by 30% by automating SQL extracts as Airflow DAGs",
           "exp1.b2", answers=["q1"])
    r = verify_bullet(b, resume, answered, jd_text=JD_TEXT)
    assert r.passed, r.flags


def test_confirmed_answer_must_be_cited(resume, answered):
    b = tb("Cut weekly reporting time by 30% by automating SQL extracts as Airflow DAGs",
           "exp1.b2")
    r = verify_bullet(b, resume, answered, jd_text=JD_TEXT)
    assert (FlagKind.NEW_TOOL, "airflow") in blocks(r)


def test_declined_answer_cannot_be_cited(resume, answered):
    b = tb("Cut weekly reporting time by 30% by automating SQL extracts with dbt",
           "exp1.b2", answers=["q2"])
    r = verify_bullet(b, resume, answered, jd_text=JD_TEXT)
    assert FlagKind.UNKNOWN_SOURCE in kinds(r)
    assert (FlagKind.NEW_TOOL, "dbt") in blocks(r)


# --- warnings -----------------------------------------------------------------------------------


def test_untraceable_wording_warns_but_passes(resume):
    r = check(resume, "Cut weekly reporting time by 30% by automating SQL extracts for the "
                      "executive board", "exp1.b2")
    warn = [f for f in r.flags if f.kind == FlagKind.NEW_CLAIM]
    assert warn and warn[0].severity == Severity.WARN and "board" in warn[0].token
    # "executive" is also a title word -> blocked separately
    assert (FlagKind.NEW_TITLE, "executive") in blocks(r)


def test_jd_wording_is_not_a_warning(resume):
    r = check(resume, "Partnered with product managers and business stakeholders on A/B test "
                      "readouts", "exp1.b3")
    assert r.flags == []


# --- summary ------------------------------------------------------------------------------------


def test_summary_may_draw_on_whole_resume(resume):
    r = verify_summary("Data analyst using SQL, Tableau and pandas to cut reporting time by "
                       "30%.", resume, jd_text=JD_TEXT)
    assert r.passed, r.flags


def test_summary_cannot_add_tools_years_or_seniority(resume):
    r = verify_summary("Senior data analyst with 8 years of Python and Snowflake experience.",
                       resume, jd_text=JD_TEXT)
    b = blocks(r)
    assert (FlagKind.NEW_TOOL, "python") in b and (FlagKind.NEW_TOOL, "snowflake") in b
    assert (FlagKind.NEW_NUMBER, "8") in b
    assert (FlagKind.NEW_TITLE, "senior") in b


@pytest.mark.parametrize("text", [
    "As senior analyst, assisted with shipment cost analysis in Excel",
    "Senior analyst who assisted with shipment cost analysis in Excel",
    "Served as a senior analyst on shipment cost analysis in Excel",
])
def test_self_claimed_title_blocked_even_if_word_is_in_source(resume, text):
    # exp2.b1 says "Assisted senior analysts": someone else's title, not the candidate's.
    r = check(resume, text, "exp2.b1")
    assert FlagKind.NEW_TITLE in kinds(r)


def test_self_claimed_title_matching_own_title_is_fine(resume):
    r = check(resume, "As data analyst, cut weekly reporting time by 30% by automating SQL "
                      "extracts", "exp1.b2")
    assert FlagKind.NEW_TITLE not in kinds(r)
