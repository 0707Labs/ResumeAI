import pytest

from app.parsing.lexicon import canonicalize, find_skills


@pytest.mark.parametrize("text, expected", [
    ("Python, C++, C# and .NET", ["python", "c++", "c#", ".net"]),
    ("Node.js with React and JS", ["node.js", "react", "javascript"]),
    ("k8s, Postgres, PySpark", ["kubernetes", "postgresql", "spark"]),
    ("Spring Boot microservices", ["spring boot", "microservices"]),
    ("CI/CD via GitHub Actions", ["ci/cd", "github actions"]),
    ("Proficient in R and SQL", ["r", "sql"]),
    ("Built REST APIs", ["rest api"]),
])
def test_finds_canonical_skills_in_order(text, expected):
    assert find_skills(text) == expected


@pytest.mark.parametrize("text", [
    "Led the R&D team",            # R inside R&D
    "Reactive design patterns",    # React inside Reactive
    "excel at communication",      # lowercase English "excel"
    "go to market strategy",       # lowercase English "go"
    "each node in the graph",      # lowercase "node"
    "the rest of the quarter",     # lowercase "rest"
    "Javanese cuisine",            # Java inside Javanese
])
def test_no_false_positives_on_english_words(text):
    assert find_skills(text) == []


def test_each_skill_reported_once():
    assert find_skills("JavaScript, JS, and more javascript") == ["javascript"]


def test_canonicalize():
    assert canonicalize("JS") == "javascript"
    assert canonicalize("Postgres") == "postgresql"
    assert canonicalize("k8s") == "kubernetes"
    assert canonicalize("Underwater basket weaving") is None
