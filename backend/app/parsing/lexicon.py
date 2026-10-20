"""Known skills and the aliases that should count as the same skill.

Canonical keys are lowercase and are what Requirement.keywords stores. Phase 5's
synonym map extends this table rather than keeping a second copy.
"""

import re
from functools import lru_cache

SKILLS: dict[str, list[str]] = {
    # languages
    "python": [],
    "java": [],
    "javascript": ["js", "ecmascript", "es6"],
    "typescript": ["ts"],
    "c++": ["cpp"],
    "c#": ["csharp"],
    "go": ["golang"],
    "rust": [],
    "ruby": [],
    "php": [],
    "kotlin": [],
    "swift": [],
    "scala": [],
    "r": [],
    "sql": [],
    "bash": ["shell scripting"],
    "html": ["html5"],
    "css": ["css3"],
    # frameworks / libraries
    "react": ["react.js", "reactjs"],
    "next.js": ["nextjs"],
    "angular": ["angularjs"],
    "vue": ["vue.js", "vuejs"],
    "node.js": ["node", "nodejs"],
    "express": ["express.js", "expressjs"],
    "django": [],
    "flask": [],
    "fastapi": [],
    "spring boot": ["spring"],
    ".net": ["dotnet"],
    "tailwind": ["tailwind css", "tailwindcss"],
    "graphql": [],
    "rest api": ["rest apis", "restful api", "restful apis", "rest", "restful"],
    "grpc": [],
    # data / ml
    "pandas": [],
    "numpy": [],
    "scikit-learn": ["sklearn", "scikit learn"],
    "tensorflow": [],
    "pytorch": [],
    "keras": [],
    "spark": ["apache spark", "pyspark"],
    "hadoop": [],
    "kafka": ["apache kafka"],
    "airflow": ["apache airflow"],
    "dbt": [],
    "machine learning": ["ml"],
    "deep learning": [],
    "nlp": ["natural language processing"],
    "computer vision": [],
    "llm": ["llms", "large language models", "large language model"],
    "statistics": ["statistical analysis"],
    "a/b testing": ["ab testing", "a/b tests", "a/b test", "ab tests", "split testing"],
    "data analysis": ["data analytics"],
    "data visualization": ["data viz"],
    "etl": ["elt", "data pipelines", "data pipeline"],
    "excel": ["microsoft excel", "ms excel"],
    "tableau": [],
    "power bi": ["powerbi"],
    "looker": [],
    # databases
    "postgresql": ["postgres", "psql"],
    "mysql": [],
    "mongodb": ["mongo"],
    "redis": [],
    "elasticsearch": ["elastic search"],
    "dynamodb": [],
    "snowflake": [],
    "bigquery": ["big query"],
    "redshift": [],
    "sqlite": [],
    # cloud / infra
    "aws": ["amazon web services"],
    "gcp": ["google cloud", "google cloud platform"],
    "azure": ["microsoft azure"],
    "docker": [],
    "kubernetes": ["k8s"],
    "terraform": [],
    "ansible": [],
    "jenkins": [],
    "github actions": [],
    "ci/cd": ["ci cd", "continuous integration", "continuous delivery", "continuous deployment"],
    "linux": [],
    "git": [],
    "microservices": ["microservice"],
    "serverless": [],
    "lambda": ["aws lambda"],
    "s3": ["amazon s3"],
    # practice / process
    "unit testing": ["unit tests", "pytest", "jest", "junit"],
    "agile": [],
    "scrum": [],
    "jira": [],
    "system design": [],
    "distributed systems": [],
    "data structures": [],
    "algorithms": [],
    "object-oriented programming": ["oop", "object oriented programming"],
    "security": ["cybersecurity", "application security"],
    "product management": [],
    "project management": [],
    "stakeholder management": [],
    "figma": [],
    "seo": [],
    "salesforce": [],
}

# Terms that are also ordinary English words or letters, so they only count
# with this exact casing ("Go", not "go to market"; "Excel", not "excel at").
CASE_SENSITIVE = {
    "go": "Go", "r": "R", "rest": "REST", "ts": "TS", "ml": "ML", "node": "Node",
    "spring": "Spring", "lambda": "Lambda", "express": "Express", "swift": "Swift",
    "excel": "Excel", "rust": "Rust", "looker": "Looker",
}

# Words that mark a line as a job title ("Senior Data Analyst").
TITLE_WORDS = {
    "engineer", "developer", "analyst", "scientist", "manager", "intern", "designer",
    "consultant", "architect", "administrator", "specialist", "associate", "lead",
    "director", "coordinator", "officer", "researcher", "programmer", "technician",
    "head", "vp", "president", "founder", "co-founder", "owner", "assistant",
    "executive", "representative", "strategist", "tester", "sde", "sre", "trainee",
    "fellow", "freelancer", "contractor", "instructor", "teacher", "editor", "writer",
}

DEGREE_WORDS = re.compile(
    r"\b(bachelor'?s?|master'?s?|ph\.?d|doctorate|mba|b\.?\s?tech|m\.?\s?tech|b\.?e\.?|"
    r"b\.?sc?|m\.?sc?|b\.?a\.?|m\.?a\.?|diploma|degree|associate'?s degree)\b",
    re.IGNORECASE,
)
INSTITUTION_WORDS = re.compile(r"\b(university|college|institute|school|academy|iit|nit)\b", re.I)
ORG_SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|corp|corporation|co|gmbh|plc|pvt|llp)\.?$", re.I)


def _pattern(term: str, case_sensitive: bool) -> re.Pattern[str]:
    body = r"[\s\-]+".join(re.escape(part) for part in term.split())
    # Custom boundaries: "c++", "c#", ".net" and "node.js" contain non-word chars,
    # and "React" must not match inside "Reactive" or "R" inside "R&D".
    pat = rf"(?<![\w+#.\-/&]){body}(?![\w+#&]|\.\w|/\w|-\w)"
    return re.compile(pat, 0 if case_sensitive else re.IGNORECASE)


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, re.Pattern[str]]]:
    out: list[tuple[str, re.Pattern[str]]] = []
    for canonical, aliases in SKILLS.items():
        for term in [canonical, *aliases]:
            if term in CASE_SENSITIVE:
                out.append((canonical, _pattern(CASE_SENSITIVE[term], case_sensitive=True)))
            else:
                out.append((canonical, _pattern(term, case_sensitive=False)))
    return out


def find_skills(text: str) -> list[str]:
    """Canonical skills mentioned in text, in order of first appearance."""
    hits: list[tuple[int, str]] = []
    for canonical, pattern in _compiled():
        m = pattern.search(text)
        if m:
            hits.append((m.start(), canonical))
    seen: list[str] = []
    for _, canonical in sorted(hits):
        if canonical not in seen:
            seen.append(canonical)
    return seen


def canonicalize(term: str) -> str | None:
    """Map a single term ("JS", "Postgres") to its canonical skill, if known."""
    found = find_skills(term.strip())
    return found[0] if len(found) == 1 else None


# Using the key skill is evidence of the listed skills, but only indirectly: a
# bullet naming "pandas" implies Python without naming it. Gap analysis treats
# these as IMPLIED, never EVIDENCED, and the tailor still can't write the
# implied skill into a bullet unless the candidate confirms it.
IMPLIES: dict[str, list[str]] = {
    "pandas": ["python", "data analysis"],
    "numpy": ["python"],
    "scikit-learn": ["python", "machine learning"],
    "pytorch": ["python", "deep learning", "machine learning"],
    "tensorflow": ["python", "deep learning", "machine learning"],
    "keras": ["python", "deep learning", "machine learning"],
    "django": ["python", "rest api"],
    "flask": ["python", "rest api"],
    "fastapi": ["python", "rest api"],
    "spring boot": ["java", "rest api"],
    "express": ["node.js", "javascript", "rest api"],
    "react": ["javascript", "html", "css"],
    "next.js": ["react", "javascript"],
    "angular": ["typescript", "javascript"],
    "vue": ["javascript"],
    "node.js": ["javascript"],
    "typescript": ["javascript"],
    "postgresql": ["sql"],
    "mysql": ["sql"],
    "sqlite": ["sql"],
    "snowflake": ["sql"],
    "bigquery": ["sql", "gcp"],
    "redshift": ["sql", "aws"],
    "dbt": ["sql", "etl"],
    "airflow": ["etl", "python"],
    "spark": ["etl", "distributed systems"],
    "kafka": ["distributed systems"],
    "tableau": ["data visualization"],
    "power bi": ["data visualization"],
    "looker": ["data visualization"],
    "a/b testing": ["statistics"],
    "lambda": ["aws", "serverless"],
    "s3": ["aws"],
    "dynamodb": ["aws"],
    "kubernetes": ["docker"],
    "github actions": ["ci/cd", "git"],
    "jenkins": ["ci/cd"],
    "scrum": ["agile"],
}


def skill_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, canonical) for every skill mention, all occurrences."""
    return sorted(
        (m.start(), m.end(), canonical)
        for canonical, pattern in _compiled()
        for m in pattern.finditer(text)
    )
