"""The synonym map: one place that decides which terms mean the same thing.

Two layers:
- Skills: canonical name -> aliases ("javascript" <- "JS", "ES6"). Lives in
  lexicon.SKILLS so parsing, gap analysis, the verifier, and the ATS scorer all
  agree. `skill_synonyms()` exposes it as a flat map.
- Wording: stem groups for ordinary words ("cut" ~ "reduced"), used by the
  verifier's untraceable-wording warning and the semantic relevance proxy.
"""

from .lexicon import CASE_SENSITIVE, SKILLS, find_skills
from .text import content_words

# Stems that count as the same idea when rewording ("cut" -> "reduced").
WORD_SYNONYMS: list[set[str]] = [
    {"build", "built", "creat", "develop", "made", "make", "produc", "implement", "set"},
    {"reduc", "cut", "lower", "decreas", "shrank", "shrink", "trim", "shorten", "sav", "saved"},
    {"increas", "grew", "grow", "boost", "rais", "improv", "lift", "expand"},
    {"clean", "prepar", "wrangl", "process", "transform", "standardiz"},
    {"analyz", "analys", "analysi", "examin", "evaluat", "assess", "investigat", "studi"},
    {"automat", "script", "schedul"},
    {"partner", "collaborat", "work", "worked", "join"},
    {"wrote", "writ", "author", "draft", "document"},
    {"report", "dashboard", "readout", "summari", "insight"},
    {"team", "group", "squad", "org"},
    {"customer", "client", "user"},
    {"time", "hour", "effort"},
    {"weekly", "week"},
    {"monthly", "month"},
    {"data", "dataset", "record"},
    {"query", "queri", "extract", "pull"},
    {"model", "forecast", "predict"},
    {"migrat", "mov", "port", "transition"},
    {"speed", "faster", "latency", "performanc", "quick", "accelerat"},
    {"test", "experiment", "trial"},
    {"stakeholder", "partner", "leader", "manag", "manager"},
    {"present", "communicat", "shar", "share"},
]


_EXTRA_WORD_SYNONYMS: list[set[str]] = [
    {"dashboard", "report", "visualiz", "chart"},
    {"stakeholder", "cross-functional", "partner"},
    {"experiment", "a/b", "test"},
    {"pipelin", "etl", "ingest", "workflow"},
    {"mentor", "coach", "onboard", "train"},
]
WORD_SYNONYMS.extend(_EXTRA_WORD_SYNONYMS)


def skill_synonyms() -> dict[str, list[str]]:
    """canonical skill -> every surface form that counts as it (for display/API)."""
    out: dict[str, list[str]] = {}
    for canonical, aliases in SKILLS.items():
        forms = [canonical, *aliases]
        out[canonical] = [CASE_SENSITIVE.get(f, f) for f in forms]
    return out


def same_skill(a: str, b: str) -> bool:
    """True when two terms name the same skill ("JS" and "JavaScript")."""
    fa, fb = find_skills(a), find_skills(b)
    return bool(fa) and fa == fb


def expand_words(words: set[str]) -> set[str]:
    """Add every stem that shares a synonym group with one already present."""
    out = set(words)
    for group in WORD_SYNONYMS:
        if out & group:
            out |= group
    return out


def related_words(text: str) -> set[str]:
    return expand_words(content_words(text))
