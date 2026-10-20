# Resume Tailor: Project Guide

## Mission
Tailor a resume to a job description (JD) WITHOUT fabricating experience,
score it for ATS fit, and give mentor-style advice.

## Non-negotiable rules
1. Never add skills, tools, metrics, titles, employers, or responsibilities
   that are not in the original resume or the candidate's explicit answers.
2. Allowed edits: reorder, reword, mirror JD terminology (only if the fact is true),
   surface existing metrics.
3. Forbidden: new tools, new numbers, inflated scope ("contributed" -> "led").
4. Every rewritten bullet must carry source_bullet_id(s). No source = rejected.
5. A separate verifier step must diff original vs tailored and flag new claims.
6. Missing JD requirements become questions to the candidate, never auto-filled.

## Architecture
Pipeline: parse resume (bullet IDs) -> parse JD -> gap analysis
(Evidenced / Implied / Missing) -> tailor -> verify -> ATS score -> mentor advice.

## ATS score (hybrid, deterministic where possible)
Required keywords 40%, preferred keywords 10%, semantic relevance 20%,
title/seniority 10%, format/parseability 10%, quantified impact 10%.
Always show the breakdown, and state that real ATS systems differ.

## Stack
- Backend: Python 3.11, FastAPI, pydantic, pdfplumber, python-docx, anthropic SDK
- Frontend: Next.js + TypeScript + Tailwind
- Tests: pytest. The anti-fabrication verifier must have strong tests.

## Conventions
- Structured JSON outputs validated with pydantic.
- API key via ANTHROPIC_API_KEY env var, never committed.
- Small commits; run tests before each commit.

## Layout
```
backend/
  app/
    main.py        FastAPI app factory, CORS, routers
    config.py      settings from env vars
    api/           HTTP routes
    models/        pydantic schemas: resume, jd, gap, tailor, ats
    parsing/       resume (PDF/DOCX) + JD parsers            (phase 2)
    analysis/      gap analysis + clarifying questions        (phase 3)
    tailoring/     tailor + anti-fabrication verifier         (phase 4)
    scoring/       hybrid ATS scorer + synonym map            (phase 5)
    mentor/        advice, verdict, upskilling plan           (phase 6)
    llm/           anthropic client wrapper                   (phase 4)
  tests/           pytest; fixtures/ holds sample resumes + JDs
frontend/          Next.js + TS + Tailwind                    (phase 7)
```

## Commands
- Setup: `cd backend && python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
- Tests: `cd backend && .venv/bin/pytest`
- Run API: `cd backend && .venv/bin/uvicorn app.main:app --reload`
