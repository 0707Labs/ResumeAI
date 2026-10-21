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
    analysis/      gap analysis, clarifying questions, optional Claude review
    tailoring/     tailor (rules + Claude w/ repair) + deterministic verifier
    scoring/       hybrid ATS scorer (synonyms in parsing/synonyms.py)
    mentor/        strengths/gaps/actions, verdict, 2-week plan, optional Claude polish
    llm/           anthropic client wrapper (claude-opus-5-5, fallbacks on)
    db/            SQLAlchemy models (auth, invites, waitlist, consent) + async session
    auth/          DB sessions (hashed tokens, rotation), cookies, CSRF, rate limits, auth event log
  alembic/         migrations; hand-written, they own the schema (models must match)
  tests/           pytest; fixtures/ holds sample resumes + JDs
frontend/
  app/             routes: / (landing), /app workspace (input, /app/analysis, /app/review, /app/score,
                   /app/mentor, /app/export), /signin, /signup/*, /legal/*; proxy.ts + app/app/layout.tsx
                   guard /app; next.config.ts redirects /login and the old step paths
  components/      AppShell, UploadDropzone, ResumePreview, ui, icons (+ later steps)
  lib/             schemas.ts (zod mirrors of pydantic; types inferred), api.ts,
                   store.ts (zustand, sessionStorage), theme.ts, diff.ts
  tests/           vitest + Testing Library; contract.test.ts hits the real backend
  e2e/             Playwright happy path against the real backend (rules-only)
```

## Commands
- Setup: `cd backend && python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
- Tests: `cd backend && .venv/bin/pytest`
- Run API: `cd backend && .venv/bin/uvicorn app.main:app --reload` (port 8000)
- Database: Postgres via `RT_DATABASE_URL` (default: local socket, db `resume_tailor`).
  `createdb resume_tailor && cd backend && .venv/bin/alembic upgrade head`.
  The app connects lazily, so the rules-only pipeline and e2e run without a DB.
  DB tests create and drop a throwaway `rt_test_*` database (`RT_TEST_ADMIN_DATABASE_URL`);
  they skip if Postgres is unreachable, except under `CI`.
- Invites and consent notices (until the admin UI exists): `cd backend && .venv/bin/python -m app.auth.cli
  create-invite [--email ...]` (prints the code once) and `... publish-notice PURPOSE VERSION URL --body-file F`.
  Dev magic-link emails land in `backend/.dev-outbox/` (gitignored), never in logs.
- Frontend: `cd frontend && npm install && npm run dev` (port 3000)
- Frontend checks: `npm test`, `npm run typecheck`, `npm run build`;
  `npm run test:contract` with the backend running validates every endpoint against the zod schemas
- E2E: `npm run test:e2e` (Playwright, Chromium; one-time `npx playwright install chromium`).
  Starts the backend in rules-only mode (empty ANTHROPIC_API_KEY) on :8000 and `npm run dev` on :3000,
  reusing servers already running there; a backend with a real key fails the spec's rules-only check.
  `E2E_WEB_URL=http://localhost:3100 E2E_API_URL=http://127.0.0.1:8100` runs a separate pair instead.
  Specs live in e2e/; Vitest only picks up tests/.
  The workspace needs an account, so every spec except landing needs Postgres (the backend's
  RT_DATABASE_URL, migrated): e2e/helpers.ts seeds invites and notices with the admin CLI and reads
  magic links from backend/.dev-outbox. A run sends 5 magic links, exactly the 5-per-15-min per-IP
  limit, which a reused backend keeps in memory: restart it (or wait) between runs.
  Point RT_DATABASE_URL at a separate migrated database when other branches share the dev one.
- Node 20 here: Vitest pinned to 4.x and jsdom to 29.x (5.x/30.x need Node 22).
  `.npmrc` sets legacy-peer-deps because npm 10 crashes on Vite 8's optional peers.

## Frontend conventions
- Validate every API response with the zod schema in lib/schemas.ts; add the schema first.
- Semantic color tokens only (bg-surface, text-muted, text-ok...); light/dark via CSS variables.
- Status is never color-only: pair it with an icon and a word.
- No network calls except our own origin: next.config.ts proxies /api/* and /health to FastAPI
  (RT_BACKEND_URL). Same origin keeps auth cookies first-party. No analytics.
- UI copy: warm, honest, mentor-like; never salesy.

## Verifier policy
- BLOCK: missing/unknown source, cross-role merge, new tool, new number (incl. rounding,
  "doubled"), new/self-claimed title, other employer, stronger verb or scope.
- WARN: content words not traceable to source, synonyms, or JD (shown, not rejected).
- Bullets diff only against their cited sources; the Skills list doesn't license a tool
  in a bullet. Confirmed candidate answers do, when cited via source_answer_ids.
- Never weaken a verifier test to make tailoring pass; fix the tailor or the prompt.

## Auth conventions
- FastAPI owns sign-in (Authlib for OAuth, joserfc for Google id_tokens). Authlib and the
  anthropic SDK use `httpx2`, not `httpx`; OAuth tests mock providers via `oauth.set_transport`
  (httpx2 MockTransport), so no test ever reaches Google or GitHub.
- Sessions are opaque random tokens; the DB stores
  only sha256 hashes (sessions, pending sign-ups, magic links, invite codes). Never store provider tokens.
- Workspace routes (lib/workspace.ts) need a session: proxy.ts redirects cookieless visitors to
  /signin?next=<path>, app/app/layout.tsx re-checks /api/me server-side, the API enforces regardless.
  `next` is allowlisted on both sides (oauth.safe_next, lib/auth safeNext); default after sign-in is /app.
- Tailoring is free to try (monthly free allowance, then a pass, Pro or a credit balance allows a run;
  nothing is spent); the clean download spends the credit. See docs/billing.md section 9.
- RT_INVITE_ONLY (default on) gates new accounts; off skips the invite step (an entered invite is still used).
- Every sign-in goes through `app.auth.sessions.start_session` (rotates session + CSRF cookie).
- State-changing auth/account endpoints depend on `rate_limit(...)` and `require_csrf`.
- Log auth events only via `log_auth_event`: user_id at most, never email, IP, code or token.
- No user row exists before invite redemption + required consent (one transaction).
- Frontend auth calls live in lib/auth.ts (AuthError codes -> copy via authMessage). Provider
  buttons follow Google/GitHub branding (official marks, brand colour tokens in globals.css).
