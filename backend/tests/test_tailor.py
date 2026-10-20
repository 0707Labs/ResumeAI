"""End-to-end tailoring with a scripted Claude that tries to fabricate.

The fake model plays the role of an over-eager tailor facing a senior JD the
candidate doesn't fully match. The pipeline must ship only verified text.
"""

import pytest

from app.analysis import analyze, apply_answers
from app.llm.client import LLMError
from app.models import ChangeType, FlagKind, ReviewStatus
from app.parsing import parse_jd, parse_resume_text
from app.parsing.lexicon import find_skills
from app.tailoring import rules_tailor, tailor
from app.tailoring.tailor import _LLMRepaired, _LLMTailored
from tests.test_verifier import RESUME

JD = """Senior Data Analyst at Northwind
Requirements
- 5+ years of SQL and Python
- Own dashboards in Tableau or Looker
- Experience with Airflow or dbt
- Statistics and A/B testing
Nice to have
- Snowflake
"""

JD_ONLY_TOOLS = {"python", "airflow", "dbt", "snowflake"}


@pytest.fixture
def resume():
    return parse_resume_text(RESUME)


@pytest.fixture
def jd():
    return parse_jd(JD)


class ScriptedLLM:
    """Returns canned outputs per schema and records every request."""

    def __init__(self, tailored=None, repaired=None, error=None):
        self.tailored, self.repaired, self.error = tailored, repaired, error
        self.calls: list[tuple[type, str]] = []

    def parse(self, *, system, user, schema, effort="medium"):
        self.calls.append((schema, user))
        if self.error:
            raise self.error
        data = self.tailored if schema is _LLMTailored else self.repaired
        if data is None:
            raise LLMError("no scripted response")
        return schema.model_validate(data)


def b(sources, text, change="reword", answers=()):
    return {"source_bullet_ids": list(sources), "source_answer_ids": list(answers),
            "text": text, "change_type": change, "jd_terms_used": []}


# Each line is a temptation the tailor gives in to. Honest ones are marked OK.
TEMPTED = [
    b(["exp1.b1"], "Led development of a churn dashboard in Tableau for customer success"),
    b(["exp1.b2"], "Cut weekly reporting time by 45% by automating SQL extracts with Airflow"),
    b(["exp1.b3"], "Partnered with product managers on A/B test readouts"),  # OK, unchanged
    b(["exp1.b4"], "Owned the migration of 14 legacy reports to Looker"),
    b(["exp1.b5"], "Saved the team 6 hours a week by cleaning order data with pandas",
      "surface_metric"),  # OK
    b(["exp2.b1"], "As senior analyst, ran shipment cost analysis in Python"),
    b(["exp2.b2"], "Built 12 recurring reports for regional operations leads"),  # OK
    b(["exp2.b3"], "Reduced late-delivery escalations by 28% by flagging at-risk routes"),  # OK
]
TEMPTED_SUMMARY = "Senior data analyst with 6+ years in SQL, Python and Snowflake."


def test_all_fabrications_blocked_and_reverted(resume, jd):
    # The repair round gives in again on two bullets and fixes the rest.
    repaired = {"bullets": [
        b(["exp1.b1"], "Built a churn dashboard in Tableau for customer success"),  # still bad
        b(["exp1.b2"], "Cut weekly reporting time by 30% by automating SQL extracts"),  # fixed
        b(["exp1.b4"], "Helped migrate 14 legacy reports to Looker", "unchanged"),  # fixed
        b(["exp2.b1"], "Assisted senior analysts with shipment cost analysis in Python"),  # bad
    ]}
    llm = ScriptedLLM({"bullets": TEMPTED, "summary": TEMPTED_SUMMARY}, repaired)
    out = tailor(resume, jd, llm=llm)

    # 1. Everything that ships is verified.
    assert all(t.verification.passed for t in out.bullets)
    # 2. No JD-only tool appears anywhere in the output.
    shipped = " ".join(t.text for t in out.bullets) + (out.summary or "")
    assert not JD_ONLY_TOOLS & set(find_skills(shipped))
    # 3. No invented numbers or inflated verbs survived.
    for bad in ("45%", "Led ", "Owned", "senior analyst,", "Built a churn"):
        assert bad not in shipped
    # 4. Every original bullet is still represented, exactly once.
    cited = sorted(s for t in out.bullets for s in t.source_bullet_ids)
    assert cited == sorted(x.id for x in resume.bullets())
    # 5. The refused text is kept for the user to see, with reasons.
    by_src = {t.source_bullet_ids[0]: t for t in out.bullets}
    churn = by_src["exp1.b1"]
    assert churn.text == resume.bullet_by_id("exp1.b1").text  # reverted
    assert [a.text for a in churn.rejected_attempts] == [
        "Led development of a churn dashboard in Tableau for customer success",
        "Built a churn dashboard in Tableau for customer success",
    ]
    blocking = {f.kind for f in churn.rejected_attempts[0].flags if f.severity == "block"}
    assert blocking == {FlagKind.INFLATED_VERB}
    cost = by_src["exp2.b1"]
    assert cost.text == resume.bullet_by_id("exp2.b1").text
    first_flags = {f.kind for f in cost.rejected_attempts[0].flags}
    assert {FlagKind.NEW_TITLE, FlagKind.NEW_TOOL} <= first_flags
    # 6. Repaired bullets ship with their history attached.
    assert by_src["exp1.b2"].text == "Cut weekly reporting time by 30% by automating SQL extracts"
    assert len(by_src["exp1.b2"].rejected_attempts) == 1
    # 7. The fabricated summary was dropped, and the note says so.
    assert out.summary is None
    assert any("summary was blocked" in n for n in out.notes)
    assert out.blocked_rewrites == 2 + 2 + 1 + 1  # attempts across the four bad bullets
    # 8. Only the failing bullets were sent back for repair.
    assert [c[0] for c in llm.calls] == [_LLMTailored, _LLMRepaired]
    repair_prompt = llm.calls[1][1]
    assert "exp1.b1" in repair_prompt and "exp1.b3" not in repair_prompt


def test_dropped_bullets_come_back(resume, jd):
    llm = ScriptedLLM({"bullets": TEMPTED[2:3]}, {"bullets": []})
    out = tailor(resume, jd, llm=llm)
    assert len(out.bullets) == len(resume.bullets())
    assert all(t.verification.passed for t in out.bullets)


def test_unsourced_bullet_is_discarded_with_note(resume, jd):
    llm = ScriptedLLM({"bullets": [
        b([], "Designed the company's Snowflake data model"),
        b(["exp9.b9"], "Shipped dbt models"),
    ]}, {"bullets": [b([], "still unsourced"), b(["exp9.b9"], "still unknown")]})
    out = tailor(resume, jd, llm=llm)
    assert all(t.verification.passed for t in out.bullets)
    assert not {"snowflake", "dbt"} & set(find_skills(" ".join(t.text for t in out.bullets)))
    assert sum("no valid source" in n for n in out.notes) == 2


def test_repair_cannot_repoint_sources(resume, jd):
    llm = ScriptedLLM(
        {"bullets": [b(["exp1.b1"], "Led a churn dashboard in Tableau")]},
        # "Fixes" it by citing a different bullet that happens to say "Built".
        {"bullets": [b(["exp2.b2"], "Built 12 recurring reports for regional operations leads")]})
    out = tailor(resume, jd, llm=llm)
    churn = next(t for t in out.bullets if t.source_bullet_ids == ["exp1.b1"])
    assert churn.text == resume.bullet_by_id("exp1.b1").text


def test_honest_summary_kept(resume, jd):
    llm = ScriptedLLM({"bullets": [], "summary":
                       "Data analyst who automates SQL reporting and builds Tableau dashboards."})
    out = tailor(resume, jd, llm=llm)
    assert out.summary and out.summary_verification.passed


def test_confirmed_answer_lets_the_tool_in(resume, jd):
    analysis = apply_answers(analyze(resume, jd), {})
    qid = next(i.question.id for i in analysis.items
               if i.question and "airflow" in i.missing_keywords)
    analysis = apply_answers(analysis, {qid: "Yes, I wrote the Airflow DAGs that ran the "
                                             "SQL extracts at Acme."})
    llm = ScriptedLLM({"bullets": [b(["exp1.b2"], "Cut weekly reporting time by 30% by "
                                     "automating SQL extracts as Airflow DAGs",
                                     answers=[qid])]})
    out = tailor(resume, jd, analysis, llm=llm)
    t = next(t for t in out.bullets if t.source_bullet_ids == ["exp1.b2"])
    assert "Airflow" in t.text and t.verification.passed and t.source_answer_ids == [qid]
    # ...and the prompt only exposed confirmed answers.
    assert "wrote the Airflow DAGs" in llm.calls[0][1]


def test_llm_failure_falls_back_to_rules(resume, jd):
    out = tailor(resume, jd, llm=ScriptedLLM(error=LLMError("Claude declined this request.")))
    assert out.notes == ["Used rules only: Claude declined this request."]
    assert [t.text for t in out.bullets] == [t.text for t in rules_tailor(resume, jd)]


# --- rules layer ---------------------------------------------------------------------------


def test_rules_reorder_within_role_by_relevance(resume, jd):
    out = tailor(resume, jd)
    exp1 = [t.source_bullet_ids[0] for t in out.bullets if t.entry_id == "exp1"]
    # Tableau, SQL, A/B testing and Looker bullets are required-keyword hits; pandas isn't.
    assert exp1.index("exp1.b5") == len(exp1) - 1
    assert all(t.verification.passed for t in out.bullets)
    assert all(t.review == ReviewStatus.PENDING for t in out.bullets)


def test_rules_never_reorder_across_roles(resume, jd):
    out = tailor(resume, jd)
    entries = [t.entry_id for t in out.bullets]
    assert entries == sorted(entries, key=lambda e: [x.id for x in resume.entries()].index(e))


def test_ids_are_sequential(resume, jd):
    out = tailor(resume, jd)
    assert [t.id for t in out.bullets] == [f"t{i}" for i in range(1, len(out.bullets) + 1)]


def test_mirroring_only_swaps_spellings():
    r = parse_resume_text("A B\nExperience\nDev | X Corp | 2020 - 2021\n"
                          "• Built charts in JS on Postgres data\n• Ran A/B test readouts")
    j = parse_jd("Engineer\nRequirements\n- JavaScript and PostgreSQL\n- A/B testing")
    out = {t.source_bullet_ids[0]: t for t in tailor(r, j).bullets}
    assert out["exp1.b1"].text == "Built charts in JavaScript on PostgreSQL data"
    assert out["exp1.b1"].change_type == ChangeType.MIRROR_TERMINOLOGY
    assert out["exp1.b2"].text == "Ran A/B test readouts"  # not "A/B testing readouts"
