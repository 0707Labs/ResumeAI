import pytest

from app.models import Priority, RequirementCategory, Seniority
from app.parsing import parse_jd
from tests.conftest import fixture_text


@pytest.fixture
def jd():
    return parse_jd(fixture_text("jd_senior_analyst.txt"))


def test_title_company_seniority(jd):
    assert jd.title == "Senior Data Analyst"
    assert jd.company == "Northwind Analytics"
    assert jd.seniority == Seniority.SENIOR
    assert jd.years_experience_min == 5


def test_responsibilities(jd):
    assert jd.responsibilities == [
        "Own the weekly business review dashboards for the operations org",
        "Partner with product and engineering on experiment design",
        "Mentor junior analysts",
    ]


def test_requirements_have_ids_and_priorities(jd):
    by_text = {r.text: r for r in jd.requirements}
    assert [r.id for r in jd.requirements] == [f"req{i}" for i in range(1, 9)]
    assert by_text["Expert SQL and strong Python (pandas)"].priority == Priority.REQUIRED
    # "is a plus" inside the Requirements section downgrades to preferred
    assert by_text["Experience with dbt or Airflow is a plus"].priority == Priority.PREFERRED
    assert by_text["Familiarity with Snowflake or BigQuery"].priority == Priority.PREFERRED


def test_benefits_are_not_requirements(jd):
    assert not any("insurance" in r.text for r in jd.requirements)


def test_keywords_and_categories(jd):
    assert jd.keywords(Priority.REQUIRED) == [
        "data analysis", "sql", "python", "pandas", "tableau", "power bi",
        "statistics", "a/b testing",
    ]
    assert jd.keywords(Priority.PREFERRED) == [
        "dbt", "airflow", "snowflake", "bigquery", "javascript",  # "JS" -> javascript
    ]
    degree = next(r for r in jd.requirements if "degree" in r.text)
    assert degree.category == RequirementCategory.EDUCATION


def test_jd_without_headings_falls_back_to_requirement_sentences():
    jd = parse_jd(fixture_text("jd_no_headings.txt"))
    assert jd.title == "Backend Engineer"
    assert jd.company == "Acme Cloud"
    assert jd.years_experience_min == 3
    assert jd.seniority == Seniority.MID  # inferred from years when title has no level
    assert jd.keywords(Priority.REQUIRED) == [
        "rest api", "go", "kubernetes", "postgresql", "distributed systems",
    ]
    assert jd.keywords(Priority.PREFERRED) == ["kafka"]  # "would help"


@pytest.mark.parametrize("title, level", [
    ("Data Science Intern", Seniority.INTERN),
    ("Junior Frontend Developer", Seniority.JUNIOR),
    ("Software Engineer II", Seniority.MID),
    ("Sr. Backend Engineer", Seniority.SENIOR),
    ("Staff Engineer", Seniority.LEAD),
    ("Principal Architect", Seniority.PRINCIPAL),
])
def test_seniority_from_title(title, level):
    assert parse_jd(f"Job Title: {title}\nRequirements\n- Python").seniority == level


def test_years_in_words():
    jd = parse_jd("Analyst\nRequirements\n- At least three years of SQL experience")
    assert jd.years_experience_min == 3


def test_paragraph_requirements_split_into_sentences():
    para = ("You have strong SQL skills and have shipped dashboards in Looker for business "
            "teams. You are comfortable with Python for analysis and automation work. "
            "You have run A/B tests end to end.")
    jd = parse_jd(f"Analyst\nWho you are\n{para}")
    assert len(jd.requirements) == 3
    assert jd.requirements[1].keywords == ["python"]
