import pytest

from app.models import ParseWarningCode, SectionKind
from app.parsing import ExtractionError, UnsupportedFileType, parse_resume_file, parse_resume_text
from tests.conftest import fixture_text


def codes(resume) -> set[ParseWarningCode]:
    return {w.code for w in resume.parse_warnings}


# --- plain text: the full structure -------------------------------------------------


@pytest.fixture
def analyst():
    return parse_resume_text(fixture_text("resume_analyst.txt"))


def test_header_fields(analyst):
    assert analyst.name == "Asha Rao"  # ALL-CAPS name is title-cased
    assert analyst.contact.email == "asha.rao@example.com"
    assert analyst.contact.phone == "+91 98765 43210"
    assert analyst.contact.links == ["linkedin.com/in/asharao"]
    assert analyst.contact.location == "Bengaluru, India"
    assert analyst.summary.startswith("Data analyst with 3 years")


def test_sections_in_order(analyst):
    assert [s.kind for s in analyst.sections] == [
        SectionKind.EXPERIENCE, SectionKind.PROJECTS, SectionKind.EDUCATION,
        SectionKind.CERTIFICATIONS,
    ]


def test_skill_categories_are_flattened(analyst):
    assert analyst.skills == ["Python", "SQL", "Tableau", "Excel", "Git"]


def test_pipe_separated_header(analyst):
    exp1 = analyst.entries()[0]
    assert (exp1.id, exp1.title, exp1.organization) == ("exp1", "Data Analyst",
                                                        "Acme Retail Pvt Ltd")
    assert (exp1.start_date, exp1.end_date) == ("Jan 2022", "Present")


def test_two_line_header_with_location(analyst):
    exp2 = analyst.entries()[1]
    assert (exp2.title, exp2.organization, exp2.location) == (
        "Junior Analyst", "Brightline Logistics", "Bengaluru, India")
    assert (exp2.start_date, exp2.end_date) == ("Jun 2020", "Dec 2021")


def test_bullet_ids_are_stable_and_scoped_to_entry(analyst):
    assert [b.id for b in analyst.bullets()] == [
        "exp1.b1", "exp1.b2", "exp1.b3", "exp2.b1", "exp2.b2", "proj1.b1", "cert1.b1",
    ]
    again = parse_resume_text(fixture_text("resume_analyst.txt"))
    assert again.model_dump() == analyst.model_dump()  # deterministic


def test_wrapped_bullet_is_joined(analyst):
    assert analyst.bullet_by_id("exp1.b1").text == (
        "Contributed to a churn dashboard in Tableau used by the customer success team")


def test_bullet_text_is_verbatim(analyst):
    # The verifier diffs against these strings; the parser must not rewrite them.
    assert analyst.bullet_by_id("exp1.b2").text == (
        "Cut weekly reporting time by 30% by automating SQL extracts")
    assert analyst.bullet_by_id("exp2.b1").text == (
        "Cleaned shipment data in Excel and Python (pandas)")


def test_project_and_education(analyst):
    proj = next(e for e in analyst.entries() if e.id == "proj1")
    assert proj.title == "Inventory Forecasting"
    edu = next(e for e in analyst.entries() if e.id == "edu1")
    assert edu.title == "B.Tech in Computer Science"
    assert edu.organization == "Visvesvaraya Technological University"
    assert (edu.start_date, edu.end_date) == ("2016", "2020")


def test_raw_text_kept_for_verifier(analyst):
    assert "Google Data Analytics Professional Certificate" in analyst.raw_text
    assert analyst.parse_warnings == []


def test_resume_without_bullet_glyphs():
    text = """Sam Lee
sam@example.com
Experience
Backend Developer, Umbrella Corp   2019 - 2023
Built internal APIs in Django for the logistics team.
Migrated reports from cron jobs to Airflow.
Education
B.Sc. Physics, State University, 2018
"""
    r = parse_resume_text(text)
    exp = r.entries()[0]
    assert (exp.title, exp.organization) == ("Backend Developer", "Umbrella Corp")
    assert [b.text for b in exp.bullets] == [
        "Built internal APIs in Django for the logistics team.",
        "Migrated reports from cron jobs to Airflow.",
    ]


def test_warns_when_no_structure():
    r = parse_resume_text("just some words without any structure at all")
    assert {ParseWarningCode.NO_SECTIONS_FOUND, ParseWarningCode.NO_BULLETS_FOUND,
            ParseWarningCode.CONTACT_MISSING} <= codes(r)


# --- PDF -----------------------------------------------------------------------------


def test_pdf_right_aligned_dates_and_wrapped_bullets(analyst_pdf):
    r = parse_resume_file(analyst_pdf, "resume.pdf")
    assert r.name == "Ravi Menon"
    assert r.contact.links == ["github.com/ravimenon"]  # the email isn't a link
    exp1, exp2 = r.entries()[:2]
    assert (exp1.title, exp1.organization, exp1.start_date, exp1.end_date) == (
        "Software Engineer", "Globex Corporation", "Mar 2021", "Present")
    assert [b.text for b in exp1.bullets] == [
        "Contributed to migrating billing services from a monolith to microservices "
        "in Java and Spring Boot",
        "Reduced p95 API latency by 40% by adding Redis caching",
    ]
    assert exp2.title == "Software Engineering Intern"
    assert r.skills == ["Java", "Python", "SQL", "Docker", "Redis"]
    assert codes(r) == set()


def test_pdf_two_columns_warns(two_column_pdf):
    r = parse_resume_file(two_column_pdf, "resume.pdf")
    assert ParseWarningCode.MULTI_COLUMN_SUSPECTED in codes(r)


def test_single_column_pdf_with_right_dates_does_not_warn(analyst_pdf):
    r = parse_resume_file(analyst_pdf, "resume.pdf")
    assert ParseWarningCode.MULTI_COLUMN_SUSPECTED not in codes(r)


def test_scanned_pdf_is_rejected(blank_pdf):
    with pytest.raises(ExtractionError, match="scanned"):
        parse_resume_file(blank_pdf, "scan.pdf")


def test_corrupt_pdf_is_rejected():
    with pytest.raises(ExtractionError):
        parse_resume_file(b"%PDF-1.4 garbage", "broken.pdf")


# --- DOCX ----------------------------------------------------------------------------


def test_docx_list_styles_tables_and_tabs(analyst_docx):
    r = parse_resume_file(analyst_docx, "resume.docx")
    assert r.name == "Meera Iyer"
    exp1, exp2 = r.entries()[:2]
    # Header came from a 2-cell table row.
    assert (exp1.title, exp1.organization, exp1.start_date) == (
        "Marketing Analyst", "Contoso Ltd", "Feb 2019")
    # "List Bullet" paragraphs have no visible glyph but are still bullets.
    assert [b.id for b in exp1.bullets] == ["exp1.b1", "exp1.b2"]
    # Tab-separated title/date line followed by an organization line.
    assert (exp2.title, exp2.organization, exp2.start_date) == (
        "Product Analyst", "Fabrikam Inc", "Jan 2017")
    edu = r.entries()[2]
    assert (edu.title, edu.organization, edu.end_date) == ("MBA", "London Business School", "2016")
    assert r.skills == ["Excel", "SQL", "Google Analytics", "Tableau"]
    assert ParseWarningCode.TABLES_DETECTED in codes(r)


# --- file handling --------------------------------------------------------------------


def test_unsupported_type():
    with pytest.raises(UnsupportedFileType):
        parse_resume_file(b"hello", "resume.pages")


def test_too_large():
    with pytest.raises(ExtractionError, match="5 MB"):
        parse_resume_file(b"a" * (5 * 1024 * 1024 + 1), "resume.txt")
