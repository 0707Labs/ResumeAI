"""Word lists the verifier uses. Kept separate so they're easy to review and extend."""

import re


def _forms(*specs: str) -> list[str]:
    """'build|built' -> explicit forms; plain 'clean' -> clean, cleans, cleaned, cleaning."""
    out: list[str] = []
    for spec in specs:
        if "|" in spec:
            out.extend(spec.split("|"))
            continue
        base = spec
        stem = base[:-1] if base.endswith("e") else base
        out += [base, base + "s", stem + "ed", stem + "ing"]
        if base.endswith("y") and not base.endswith(("ay", "ey", "oy")):
            out += [base[:-1] + "ied", base[:-1] + "ies"]
    return out


# Rule 3: verb strength. A rewrite may not climb above the strongest verb in its
# sources ("contributed to" -> "built" or "led" is inflation).
SUPPORT_VERBS = _forms(
    "assist", "help|helps|helped|helping", "support", "contribute", "participate",
    "collaborate", "partner", "aid", "shadow", "involved", "worked on|worked with|working on",
    "was part of|part of", "exposure to",
)
DOING_VERBS = _forms(
    "build|builds|built|building", "develop", "create", "implement", "design", "write|wrote|"
    "written|writes|writing", "analyze", "analyse", "deliver", "automate", "improve", "reduce",
    "increase", "clean", "train", "deploy", "migrate", "optimize", "cut|cuts|cutting",
    "grow|grew|grown|grows|growing", "test", "prepare", "maintain", "refactor", "integrate",
    "launch", "presented|presenting", "researched", "modeled|modelled|modeling",
    "forecasted", "queried|querying", "configure", "documented|documenting", "debug", "fix",
    "monitored|monitoring", "reviewed|reviewing", "conduct", "run|ran|runs|running",
    "set up|sets up|setting up", "ship|shipped|shipping|ships", "authored", "produce",
    "processed|processing", "transform", "visualize", "reported", "standardize", "streamline",
    "schedule", "collect", "gather", "audit", "evaluate", "assess", "identify", "resolve",
    "investigate", "measure", "tracked|tracking", "coordinate", "organize", "planned",
    "tested|testing",
    "draft", "calculate", "compile", "generate", "upgrade", "scale", "secure", "translate",
    "convert", "cleaned up|clean up",
)
OWNING_VERBS = (
    _forms("own|owned|owning|owns", "manage", "spearhead", "oversee|oversaw|overseen|oversees|"
           "overseeing", "architected|architecting", "champion", "orchestrate", "supervise",
           "mentor", "coach", "pioneer", "establish", "direct|directed|directing",
           "founded|co-founded", "headed|heading up", "drove|driven|driving", "chair")
    + ["led", "leading", "in charge of", "responsible for", "accountable for", "ran the team"]
)
SCOPE_INFLATORS = [
    "single-handedly", "singlehandedly", "independently", "solely", "sole", "alone",
    "end-to-end", "end to end", "company-wide", "companywide", "org-wide",
    "organization-wide", "organisation-wide", "enterprise-wide", "firm-wide", "globally",
    "from scratch", "entire",
]

_LEVELS = [(3, OWNING_VERBS), (2, DOING_VERBS), (1, SUPPORT_VERBS)]


def _phrase_re(phrases: list[str]) -> re.Pattern[str]:
    alts = sorted({re.escape(p).replace(r"\ ", r"\s+") for p in phrases}, key=len, reverse=True)
    return re.compile(rf"(?<![\w-])(?:{'|'.join(alts)})(?![\w-])", re.IGNORECASE)


_LEVEL_RES = [(lvl, _phrase_re(words)) for lvl, words in _LEVELS]
# "Lead" as a sentence-initial verb; elsewhere "lead" is usually the noun (title check).
_LEAD_START = re.compile(r"^\s*lead\b", re.IGNORECASE)
SCOPE_RE = _phrase_re(SCOPE_INFLATORS)


def verb_level(text: str) -> tuple[int, str | None]:
    """(claim strength, the word that set it); 0 when no ladder verb appears.

    The leftmost ladder verb governs ("Helped run reporting" is support, level 1),
    except that an ownership verb anywhere is always level 3 ("Built X and led Y").
    """
    if _LEAD_START.search(text):
        return 3, "Lead"
    owning = _LEVEL_RES[0][1].search(text)
    if owning:
        return 3, owning.group(0)
    hits = [(m.start(), lvl, m.group(0)) for lvl, pattern in _LEVEL_RES[1:]
            for m in [pattern.search(text)] if m]
    if not hits:
        return 0, None
    _, lvl, word = min(hits)
    return lvl, word


TITLE_RE = re.compile(
    r"(?<![\w-])(senior|sr\.|junior|principal|staff engineer|chief|head of|director|"
    r"managers?|vp|vice president|supervisors?|architect|team lead|tech lead|lead "
    r"(?:engineer|analyst|developer|designer|scientist)|founder|co-founder|president|"
    r"intern|executive)(?![\w-])",
    re.IGNORECASE,
)

# The candidate claiming a title: "As senior analyst, ...", "Promoted to lead",
# "Served as manager", or a bullet that opens with a title word.
SELF_TITLE_RE = re.compile(
    rf"(?:^\s*|\bas\s+(?:an?\s+|the\s+)?|\bpromoted\s+to\s+(?:an?\s+|the\s+)?|"
    rf"\bserv(?:ed|ing)\s+as\s+(?:an?\s+|the\s+)?|\bacting\s+)(?:{TITLE_RE.pattern})",
    re.IGNORECASE,
)

# Connective words a rewrite may add freely.
FILLER = {
    "result", "resulting", "enabl", "enable", "ensur", "ensure", "support", "deliver",
    "key", "core", "multiple", "several", "various", "new", "existing", "including",
    "through", "throughout", "among", "between", "toward", "towards", "help", "allow",
    "making", "used", "based", "driven", "focused", "related", "relevant", "accurate",
    "accuracy", "clear", "timely", "consistent", "reliable", "efficient", "effectiv",
    "regular", "recurring", "ongoing", "daily", "business", "decision", "decisions",
    "insight", "insights", "impact", "outcome", "outcomes", "quality", "process", "workflow",
    "workflows", "solution", "solutions", "approach", "initiative", "initiatives", "effort",
}
