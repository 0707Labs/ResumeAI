import pytest
from pydantic import ValidationError

from app.models import (
    WEIGHTS,
    ATSReport,
    Bullet,
    ChangeType,
    ClarifyingQuestion,
    Entry,
    FlagKind,
    GapItem,
    GapStatus,
    JobDescription,
    Priority,
    Requirement,
    Resume,
    ScoreComponent,
    Section,
    SectionKind,
    TailoredBullet,
    VerificationFlag,
    VerificationResult,
)


def make_resume() -> Resume:
    return Resume(
        name="Asha Rao",
        skills=["Python", "SQL"],
        sections=[
            Section(
                kind=SectionKind.EXPERIENCE,
                heading="Experience",
                entries=[
                    Entry(
                        id="exp1",
                        title="Data Analyst",
                        organization="Acme",
                        bullets=[
                            Bullet(id="exp1.b1", text="Contributed to a churn dashboard in SQL"),
                            Bullet(id="exp1.b2", text="Cut report time by 30%"),
                        ],
                    )
                ],
            )
        ],
    )


# --- Resume ---------------------------------------------------------------


def test_resume_lookup_helpers():
    r = make_resume()
    assert [b.id for b in r.bullets()] == ["exp1.b1", "exp1.b2"]
    assert r.bullet_by_id("exp1.b2").text == "Cut report time by 30%"
    assert r.bullet_by_id("nope") is None
    assert r.entry_for_bullet("exp1.b1").organization == "Acme"


def test_resume_rejects_duplicate_bullet_ids():
    with pytest.raises(ValidationError, match="duplicate id"):
        Resume(
            sections=[
                Section(
                    kind=SectionKind.EXPERIENCE,
                    heading="Experience",
                    entries=[
                        Entry(id="exp1", bullets=[Bullet(id="exp1.b1", text="a")]),
                        Entry(id="exp2", bullets=[Bullet(id="exp1.b1", text="b")]),
                    ],
                )
            ]
        )


@pytest.mark.parametrize("bad_id", ["", "B1", "exp1.x1", "exp 1", "1exp"])
def test_bullet_id_format(bad_id):
    with pytest.raises(ValidationError):
        Bullet(id=bad_id, text="x")


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        Bullet(id="exp1.b1", text="x", invented_metric="50%")


def test_resume_roundtrips_through_json():
    r = make_resume()
    assert Resume.model_validate_json(r.model_dump_json()) == r


# --- JobDescription ---------------------------------------------------------


def test_jd_keywords_by_priority_dedupes():
    jd = JobDescription(
        title="Senior Data Analyst",
        requirements=[
            Requirement(id="req1", text="SQL", priority=Priority.REQUIRED, keywords=["sql"]),
            Requirement(id="req2", text="SQL + Python", priority=Priority.REQUIRED,
                        keywords=["sql", "python"]),
            Requirement(id="req3", text="Tableau", priority=Priority.PREFERRED,
                        keywords=["tableau"]),
        ],
    )
    assert jd.keywords(Priority.REQUIRED) == ["sql", "python"]
    assert jd.keywords(Priority.PREFERRED) == ["tableau"]


def test_jd_rejects_duplicate_requirement_ids():
    req = Requirement(id="req1", text="SQL", priority=Priority.REQUIRED)
    with pytest.raises(ValidationError):
        JobDescription(requirements=[req, req])


# --- GapItem (rule 6) ---------------------------------------------------------


def test_missing_gap_requires_question_and_no_evidence():
    q = ClarifyingQuestion(id="q1", requirement_id="req1", question="Have you used Airflow?")
    item = GapItem(requirement_id="req1", requirement_text="Airflow",
                   status=GapStatus.MISSING, question=q)
    assert item.question.answer is None

    with pytest.raises(ValidationError, match="clarifying question"):
        GapItem(requirement_id="req1", requirement_text="Airflow", status=GapStatus.MISSING)
    with pytest.raises(ValidationError, match="cannot cite evidence"):
        GapItem(requirement_id="req1", requirement_text="Airflow", status=GapStatus.MISSING,
                evidence_bullet_ids=["exp1.b1"], question=q)


@pytest.mark.parametrize("status", [GapStatus.EVIDENCED, GapStatus.IMPLIED])
def test_evidenced_and_implied_require_evidence(status):
    with pytest.raises(ValidationError, match="at least one piece of evidence"):
        GapItem(requirement_id="req1", requirement_text="SQL", status=status)
    GapItem(requirement_id="req1", requirement_text="SQL", status=status,
            evidence_bullet_ids=["exp1.b1"])


def test_gap_question_must_match_requirement():
    q = ClarifyingQuestion(id="q1", requirement_id="req9", question="?")
    with pytest.raises(ValidationError, match="must match"):
        GapItem(requirement_id="req1", requirement_text="x", status=GapStatus.MISSING, question=q)


# --- TailoredBullet / verification -------------------------------------------


def test_unsourced_bullet_still_parses_so_verifier_can_flag_it():
    tb = TailoredBullet(id="t1", text="Led a churn dashboard", change_type=ChangeType.REWORD)
    assert tb.source_bullet_ids == []


def test_verification_passed_is_derived_from_flags():
    assert VerificationResult().passed is True
    flagged = VerificationResult(flags=[
        VerificationFlag(kind=FlagKind.INFLATED_VERB, token="led", detail="was 'contributed'")
    ])
    assert flagged.passed is False


def test_cannot_forge_passed_flag():
    # A client (or LLM) sending passed=true alongside flags must not override the check.
    data = {"flags": [{"kind": "new_tool", "token": "Kubernetes", "detail": "not in resume"}],
            "passed": True}
    assert VerificationResult.model_validate(data).passed is False


# --- ATSReport -----------------------------------------------------------------


def full_report(score: float) -> ATSReport:
    return ATSReport(components=[ScoreComponent(name=c, score=score) for c in WEIGHTS])


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_ats_total_is_weighted():
    assert full_report(1.0).total == 100.0
    assert full_report(0.5).total == 50.0
    comps = [ScoreComponent(name=c, score=1.0 if c == "required_keywords" else 0.0)
             for c in WEIGHTS]
    assert ATSReport(components=comps).total == 40.0


def test_ats_report_requires_every_component_exactly_once():
    comps = [ScoreComponent(name=c, score=1.0) for c in WEIGHTS]
    with pytest.raises(ValidationError):
        ATSReport(components=comps[:-1])
    with pytest.raises(ValidationError):
        ATSReport(components=[*comps, comps[0]])


def test_ats_score_bounds():
    with pytest.raises(ValidationError):
        ScoreComponent(name="required_keywords", score=1.2)


def test_ats_report_has_disclaimer_and_roundtrips():
    report = full_report(0.7)
    assert "estimate" in report.disclaimer
    dumped = report.model_dump()
    assert dumped["total"] == 70.0 and dumped["components"][0]["weight"] == 0.4
    assert ATSReport.model_validate(dumped) == report
