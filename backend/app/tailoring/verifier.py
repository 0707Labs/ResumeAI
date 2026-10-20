"""Anti-fabrication verifier (rule 5).

Diffs each tailored bullet against exactly the sources it cites, meaning the
original bullets (by id) and confirmed candidate answers (by question id), and
flags anything new.

BLOCK flags reject the rewrite:
  missing/unknown source, cross-entry merge, new tool, new number, new title,
  new employer, inflated verb or scope.
WARN flags pass but are shown for review:
  content words that don't trace to the source, its synonyms, or the JD.

Deterministic on purpose: the same input always gets the same verdict, and
nothing the tailoring model says can turn a flag off.
"""

import re
from dataclasses import dataclass

from app.models import (
    AnswerKind,
    FlagKind,
    GapAnalysis,
    Resume,
    Severity,
    TailoredBullet,
    VerificationFlag,
    VerificationResult,
)
from app.parsing.lexicon import ORG_SUFFIX, canonicalize, find_skills, skill_spans
from app.parsing.text import content_words, stem

from app.parsing.synonyms import expand_words

from .vocab import FILLER, SCOPE_RE, SELF_TITLE_RE, TITLE_RE, verb_level

# --- numbers --------------------------------------------------------------------------

_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUMBER_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
                      "thousand": 1000, "dozen": 12, "dozens": 12})
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9,
          "bn": 1e9, "billion": 1e9, "lakh": 1e5, "lakhs": 1e5, "crore": 1e7, "crores": 1e7}
_NUM_RE = re.compile(
    r"(?<![\w.])(?P<cur>[$€£₹])?\s?(?P<num>\d+(?:,\d{3})*(?:\.\d+)?)\s?"
    r"(?P<unit>%|percent\b|x\b|k\b|mm\b|m\b|bn\b|b\b|million\b|billion\b|thousand\b|"
    r"lakhs?\b|crores?\b)?(?![A-Za-z\d])",
    re.IGNORECASE,
)
_WORD_NUM_RE = re.compile(rf"\b({'|'.join(_NUMBER_WORDS)})\b", re.IGNORECASE)
_MULTIPLIER_WORDS = {"doubled": 2, "doubling": 2, "tripled": 3, "tripling": 3,
                     "quadrupled": 4, "halved": 0.5}


@dataclass(frozen=True)
class Quantity:
    value: float
    kind: str  # "percent" | "money" | "multiple" | "plain"
    raw: str


def quantities(text: str) -> list[Quantity]:
    out: list[Quantity] = []
    for m in _NUM_RE.finditer(text):
        value = float(m.group("num").replace(",", ""))
        unit = (m.group("unit") or "").lower()
        kind = "plain"
        if unit in ("%", "percent"):
            kind = "percent"
        elif unit == "x":
            kind = "multiple"
        elif unit in _SCALE:
            value *= _SCALE[unit]
        if m.group("cur"):
            kind = "money"
        out.append(Quantity(value, kind, m.group(0).strip()))
    for m in _WORD_NUM_RE.finditer(text):
        out.append(Quantity(float(_NUMBER_WORDS[m.group(1).lower()]), "plain", m.group(0)))
    for word, mult in _MULTIPLIER_WORDS.items():
        for m in re.finditer(rf"\b{word}\b", text, re.IGNORECASE):
            out.append(Quantity(float(mult), "multiple", m.group(0)))
            if mult == 0.5:
                out.append(Quantity(50.0, "percent", m.group(0)))
            elif mult == 2:
                out.append(Quantity(100.0, "percent", m.group(0)))
    return out


def _same(a: Quantity, b: Quantity) -> bool:
    kinds_ok = a.kind == b.kind or {a.kind, b.kind} == {"plain", "money"}
    return kinds_ok and abs(a.value - b.value) < 1e-9


# --- proper nouns / acronyms ----------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z][\w+#./&-]*[\w+#]|[A-Za-z]")
_ALWAYS_OK = {"I", "A"}


def _name_like_tokens(text: str) -> list[tuple[int, str]]:
    """Tokens that look like names, products, or acronyms (excluding the first word)."""
    out = []
    for i, m in enumerate(_TOKEN_RE.finditer(text)):
        tok = m.group(0).rstrip(".")
        if tok in _ALWAYS_OK:
            continue
        sentence_start = i == 0 or re.search(r"[.;:!?]\s*$", text[: m.start()])
        inner_caps = any(c.isupper() for c in tok[1:])
        has_digit = any(c.isdigit() for c in tok)
        capitalized = tok[0].isupper()
        if inner_caps or has_digit or (capitalized and not sentence_start):
            out.append((m.start(), tok))
    return out


# --- source assembly --------------------------------------------------------------------


@dataclass
class Sources:
    texts: list[str]  # cited bullets + confirmed answers
    titles: list[str]  # titles of the cited entries
    own_orgs: list[str]  # organizations of the cited entries
    other_orgs: list[str]  # every other organization on the resume
    # Where title/seniority words may come from. None = all of the above. A summary
    # describes the candidate, so "senior" must come from their own job titles,
    # not from a bullet like "assisted senior analysts".
    title_texts: list[str] | None = None

    @property
    def joined(self) -> str:
        return "\n".join([*self.texts, *self.titles, *self.own_orgs])


def confirmed_answers(analysis: GapAnalysis | None) -> dict[str, str]:
    if analysis is None:
        return {}
    return {q.id: q.answer for q in analysis.questions()
            if q.answer and q.answer_kind == AnswerKind.CONFIRMED}


def _block(kind: FlagKind, token: str, detail: str) -> VerificationFlag:
    return VerificationFlag(kind=kind, token=token, detail=detail)


# --- entry points -------------------------------------------------------------------------


def verify_bullet(bullet: TailoredBullet, resume: Resume, analysis: GapAnalysis | None = None,
                  jd_text: str = "") -> VerificationResult:
    flags: list[VerificationFlag] = []
    answers = confirmed_answers(analysis)
    all_questions = {q.id for q in analysis.questions()} if analysis else set()

    if not bullet.source_bullet_ids:
        flags.append(_block(FlagKind.MISSING_SOURCE, "", "No source bullet cited (rule 4)."))
    texts, entries = [], []
    for bid in bullet.source_bullet_ids:
        src = resume.bullet_by_id(bid)
        if src is None:
            flags.append(_block(FlagKind.UNKNOWN_SOURCE, bid,
                                f"Cites {bid}, which isn't in the resume."))
            continue
        texts.append(src.text)
        entry = resume.entry_for_bullet(bid)
        if entry and entry not in entries:
            entries.append(entry)
    for qid in bullet.source_answer_ids:
        if qid in answers:
            texts.append(answers[qid])
        else:
            why = "wasn't confirmed by the candidate" if qid in all_questions else "doesn't exist"
            flags.append(_block(FlagKind.UNKNOWN_SOURCE, qid, f"Cites answer {qid}, which {why}."))
    if len(entries) > 1:
        flags.append(_block(FlagKind.CROSS_ENTRY, ", ".join(e.id for e in entries),
                            "Merges bullets from different roles; each claim must stay "
                            "with the job it happened at."))
    if not texts:
        return VerificationResult(flags=flags)  # nothing to diff against

    own_ids = {e.id for e in entries}
    sources = Sources(
        texts=texts,
        titles=[e.title for e in entries if e.title],
        own_orgs=[e.organization for e in entries if e.organization],
        other_orgs=[e.organization for e in resume.entries()
                    if e.organization and e.id not in own_ids],
    )
    flags.extend(check_text(bullet.text, sources, jd_text))
    return VerificationResult(flags=flags)


def verify_summary(text: str, resume: Resume, analysis: GapAnalysis | None = None,
                   jd_text: str = "") -> VerificationResult:
    """A summary draws on the whole resume, so the whole resume is its source."""
    sources = Sources(
        texts=[resume.raw_text, resume.summary or "", ", ".join(resume.skills),
               *confirmed_answers(analysis).values()],
        titles=[e.title for e in resume.entries() if e.title],
        own_orgs=[e.organization for e in resume.entries() if e.organization],
        other_orgs=[],
        title_texts=[*(e.title for e in resume.entries() if e.title), resume.summary or ""],
    )
    return VerificationResult(flags=check_text(text, sources, jd_text))


def check_text(text: str, sources: Sources, jd_text: str = "") -> list[VerificationFlag]:
    flags: list[VerificationFlag] = []
    src = sources.joined

    # 1. Tools / skills: canonical match, so "JS" -> "JavaScript" is fine.
    src_skills = set(find_skills(src))
    for skill in find_skills(text):
        if skill not in src_skills:
            flags.append(_block(FlagKind.NEW_TOOL, skill,
                                f'"{skill}" isn\'t in the cited source.'))

    # 2. Unrecognized names / acronyms / employers.
    spans = skill_spans(text)
    src_tokens = {t.lower().rstrip(".") for t in _TOKEN_RE.findall(src)}
    other_orgs = [o for o in sources.other_orgs if o]
    flagged_orgs: set[str] = set()
    for org in other_orgs:
        if re.search(rf"(?<!\w){re.escape(org)}(?!\w)", text, re.I) and \
                org.lower() not in src.lower():
            flags.append(_block(FlagKind.NEW_EMPLOYER, org,
                                f'Mentions {org}, which is a different role on your resume.'))
            flagged_orgs.update(w.lower() for w in org.split())
    for pos, tok in _name_like_tokens(text):
        if any(s <= pos < e for s, e, _ in spans):
            continue  # a known skill; handled above
        low = tok.lower()
        if low in src_tokens or low in flagged_orgs or canonicalize(tok):
            continue
        if ORG_SUFFIX.search(tok) or any(low in o.lower().split() for o in other_orgs):
            flags.append(_block(FlagKind.NEW_EMPLOYER, tok, f'"{tok}" isn\'t in the source.'))
        else:
            flags.append(_block(FlagKind.NEW_TOOL, tok,
                                f'"{tok}" (a name or acronym) isn\'t in the cited source.'))

    # 3. Numbers: every quantity must match one in the source, same kind.
    src_q = quantities(src)
    for q in quantities(text):
        if not any(_same(q, s) for s in src_q):
            flags.append(_block(FlagKind.NEW_NUMBER, q.raw,
                                f'"{q.raw}" doesn\'t appear in the cited source.'))

    # 4. Titles / seniority.
    title_src = src if sources.title_texts is None else "\n".join(sources.title_texts)
    src_titles = {stem(m.lower()) for m in TITLE_RE.findall(title_src)}
    for m in TITLE_RE.finditer(text):
        if stem(m.group(0).lower()) not in src_titles:
            flags.append(_block(FlagKind.NEW_TITLE, m.group(0),
                                f'"{m.group(0)}" implies a title or seniority the source '
                                f'doesn\'t state.'))

    # A self-claimed title must match the candidate's own job title, even when
    # the source mentions that title for someone else ("assisted senior analysts").
    own_titles = {stem(m.lower()) for t in sources.titles for m in TITLE_RE.findall(t)}
    for m in SELF_TITLE_RE.finditer(text):
        word = m.group(1)
        if stem(word.lower()) not in own_titles:
            flags.append(_block(FlagKind.NEW_TITLE, word,
                                f'Presents you as "{word}", which isn\'t your title for this '
                                f'role.'))

    # 5. Verb strength and scope (rule 3).
    new_lvl, new_word = verb_level(text)
    src_lvl = max((verb_level(t)[0] or 2) for t in sources.texts)
    if new_lvl > src_lvl:
        _, src_word = max((verb_level(t) for t in sources.texts), key=lambda x: x[0])
        flags.append(_block(FlagKind.INFLATED_VERB, new_word or "",
                            f'"{new_word}" claims more than the source'
                            f'{f" ({src_word!r})" if src_word else ""}.'))
    for m in SCOPE_RE.finditer(text):
        if not re.search(rf"(?<![\w-]){re.escape(m.group(0))}(?![\w-])", src, re.I):
            flags.append(_block(FlagKind.INFLATED_VERB, m.group(0),
                                f'"{m.group(0)}" inflates scope beyond the source.'))

    # 6. Untraceable wording (warning only).
    novel = _novel_words(text, src, jd_text)
    if novel:
        flags.append(VerificationFlag(
            kind=FlagKind.NEW_CLAIM, token=", ".join(novel),
            detail="These words don't trace to the source or the JD; check they're true.",
            severity=Severity.WARN))
    return _dedupe(flags)


def _novel_words(text: str, src: str, jd_text: str) -> list[str]:
    allowed = expand_words(content_words(src) | content_words(jd_text))
    # Skill names and numbers are judged by the stricter checks above.
    stripped = text
    for s, e, _ in reversed(skill_spans(text)):
        stripped = stripped[:s] + " " + stripped[e:]
    return sorted(content_words(stripped) - allowed - FILLER)[:6]


def _dedupe(flags: list[VerificationFlag]) -> list[VerificationFlag]:
    seen, out = set(), []
    for f in flags:
        key = (f.kind, f.token.lower())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
