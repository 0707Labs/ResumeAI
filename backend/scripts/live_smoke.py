"""Run the whole pipeline against the real Claude API and print what happened.

    cd backend && .venv/bin/python scripts/live_smoke.py [sample|nina|all]

Needs ANTHROPIC_API_KEY in the environment or in backend/.env. Costs real tokens:
each case makes about five Claude calls (gap review, tailor, maybe a repair,
two semantic scores, mentor polish).
"""

import logging
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


def _load_dotenv() -> None:
    env = BACKEND / ".env"
    if os.environ.get("ANTHROPIC_API_KEY") or not env.exists():
        return
    for line in env.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

from app.analysis import analyze, refine_with_llm  # noqa: E402
from app.llm.client import ClaudeLLM  # noqa: E402
from app.mentor import build_advice, polish  # noqa: E402
from app.parsing import parse_jd, parse_resume_text  # noqa: E402
from app.scoring import score  # noqa: E402
from app.tailoring import apply_tailoring, tailor  # noqa: E402
from tests.test_tailor import JD as NINA_JD  # noqa: E402
from tests.test_verifier import RESUME as NINA_RESUME  # noqa: E402

SAMPLES = BACKEND / "app" / "samples"
CASES = {
    "sample": ((SAMPLES / "resume.txt").read_text(), (SAMPLES / "jd.txt").read_text()),
    "nina": (NINA_RESUME, NINA_JD),
}


def _blocks(flags) -> str:
    return "; ".join(f"{f.kind.value}: {f.detail}" for f in flags if f.severity == "block")


def run(name: str, resume_text: str, jd_text: str, llm: ClaudeLLM) -> dict:
    print(f"\n{'=' * 30} {name} {'=' * 30}")
    resume, jd = parse_resume_text(resume_text), parse_jd(jd_text)
    print(f"Parsed {len(resume.bullets())} bullets; JD '{jd.title}' with "
          f"{len(jd.requirements)} requirements")

    analysis, note = refine_with_llm(analyze(resume, jd), resume, llm)
    print(f"\n[gap] {note}")
    for item in analysis.items:
        print(f"  {item.status.value:9} ({item.decided_by}) {item.requirement_text}")

    tailored = tailor(resume, jd, analysis, llm)
    print("\n[tailor] notes:")
    for n in tailored.notes:
        print(f"  - {n}")
    accepted = blocked = 0
    for b in tailored.bullets:
        for a in b.rejected_attempts:
            blocked += 1
            print(f"  BLOCKED  {a.text}\n           -> {_blocks(a.flags)}")
        if b.change_type.value not in ("unchanged", "reorder") and b.verification.passed:
            accepted += 1
            warns = [f.detail for f in b.verification.flags]
            print(f"  ACCEPTED [{b.change_type.value}] {b.text}\n"
                  f"           was: {b.original_text}"
                  + (f"\n           warn: {'; '.join(warns)}" if warns else ""))
    print(f"  summary: {tailored.summary!r}")
    shipped_blocks = [b for b in tailored.bullets if not b.verification.passed]
    print(f"  shipped bullets failing verification: {len(shipped_blocks)}")

    before = score(resume, jd, llm=llm)
    after = score(apply_tailoring(resume, tailored), jd, llm=llm)
    print(f"\n[score] before {before.total} -> after {after.total}")
    for c in after.components:
        print(f"  {c.name.value:22} {c.score:.2f}  {c.notes}")

    advice = polish(build_advice(resume, jd, analysis, after), llm)
    print(f"\n[mentor] {advice.verdict.headline}")
    for n in advice.notes:
        print(f"  - {n}")
    return {"accepted": accepted, "blocked_attempts": blocked,
            "shipped_failing": len(shipped_blocks)}


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY (env or backend/.env) first.")
        return 2
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("app.mentor.polish").setLevel(logging.INFO)
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = list(CASES) if which == "all" else [which]
    llm = ClaudeLLM()
    results = {n: run(n, *CASES[n], llm) for n in names}

    print(f"\n{'=' * 30} usage {'=' * 30}")
    for schema, inp, out in llm.usage:
        print(f"  {schema:14} in={inp:6} out={out:6}")
    print(f"  total: {len(llm.usage)} calls, in={sum(u[1] for u in llm.usage)}, "
          f"out={sum(u[2] for u in llm.usage)}")
    for n, r in results.items():
        print(f"  {n}: {r}")
    return 1 if any(r["shipped_failing"] for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
