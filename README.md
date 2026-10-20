# Resume Tailor

Tailor a resume to a job description **without fabricating experience**, score it
for ATS fit, and get mentor-style advice on whether to apply and what to learn.

Every rewritten bullet cites the original bullet(s) it came from, and a
deterministic verifier blocks anything new: tools, numbers, titles, employers, or
stronger verbs. Missing requirements become questions to you; only your own
answers can add a fact.

## Quick start

Backend (Python 3.11):

```bash
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload
```

Frontend (Node 20.9+):

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:3000 and click **Use the sample resume and JD** to try it.

### Claude (optional)

Everything works rules-only. To let Claude review unclear gaps, rewrite bullets,
judge semantic relevance, and polish mentor wording, set `ANTHROPIC_API_KEY` in the
backend's environment (see `backend/.env.example`). Claude output always goes back
through the same verifier, and blocked rewrites fall back to your original wording.
Calls use `claude-opus-5-5` with server-side refusal fallbacks enabled.

## How it works

1. **Parse** the resume (PDF/DOCX/TXT) into sections, entries, and bullets with
   stable IDs (`exp1.b2`), plus format warnings. Parse the JD into required and
   preferred requirements with normalized keywords.
2. **Gap analysis** marks each requirement Evidenced, Implied, or Missing, and asks
   neutral questions for anything not evidenced.
3. **Tailor**: reorder by relevance, mirror JD spellings, and (with Claude) reword.
   The **verifier** checks each bullet against only its cited sources.
4. **Review**: approve, reject, or edit each bullet in a word diff. Edits are
   re-verified, and you can cite your confirmed answers.
5. **ATS score**: required keywords 40%, preferred 10%, semantic relevance 20%,
   title/seniority 10%, format 10%, quantified impact 10%, before vs after.
   Real ATS systems differ; treat it as an estimate.
6. **Mentor**: strengths, ranked gaps, actions, a should-you-apply verdict, and a
   two-week upskilling plan.
7. **Export** DOCX or PDF. Only approved bullets that re-verify on the server use
   tailored wording.

## Tests

```bash
cd backend && .venv/bin/pytest
```

```bash
cd frontend && npm test && npm run typecheck && npm run build
```
