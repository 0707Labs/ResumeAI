# Run and test Resume Tailor locally

A step-by-step guide from an empty machine to a signed-in user area and a working admin
dashboard, then a checklist of what to try, the automated tests, and fixes for the usual
snags. Everything here runs on your laptop: email goes to a folder instead of an inbox,
payments stay off unless you add Dodo test keys, and Claude is optional.

Time: about 20 minutes the first time.

---

## 0. What you need

| Tool | Version | Check | Install (macOS) |
|---|---|---|---|
| Python | 3.11 or newer | `python3.11 --version` | `brew install python@3.11` |
| Node.js | 20.9 or newer | `node --version` | `brew install node@20` |
| PostgreSQL | 15 or newer | `psql --version` | `brew install postgresql@16` |
| Git | any | `git --version` | `xcode-select --install` |

Start Postgres and leave it running:

```bash
brew services start postgresql@16
```

Check it answers (prints a version line):

```bash
psql -d postgres -c "select version();"
```

> On Linux, install the same versions with your package manager and make sure your
> user can create databases (`sudo -u postgres createuser --superuser $USER`).

## 1. Get the code

The user area and admin dashboard live on the `admin/ops` branch (it includes every
earlier step). From the repository root:

```bash
git fetch && git switch admin/ops
```

All commands below run from the repository root unless a step says `cd backend` or
`cd frontend`. Use **two terminal tabs**: one for the backend, one for the frontend.

## 2. Create the database

```bash
createdb resume_tailor
```

That's the name the backend uses by default. The first migration also creates a
Postgres role called `rt_app` that signed-in requests run as (row-level security). Your
local Postgres user can create roles, so there's nothing to do for it here; on a managed
database see [admin.md section 4](admin.md#4-row-level-security).

## 3. Set up the backend

**Terminal 1:**

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
```

Open `backend/.env` and set these (leave everything else as it is):

| Setting | Value for local testing |
|---|---|
| `RT_AUTH_SECRET` | a long random string: run `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` and paste the output |
| `RT_DATABASE_URL` | `postgresql+psycopg:///resume_tailor` (already set) |
| `RT_PUBLIC_URL` | `http://localhost:3000` (already set) |
| `CORS_ORIGINS` | `http://localhost:3000` (already set) |
| `RT_MAILER` | `outbox` (already set): sign-in emails are written to `backend/.dev-outbox/` |
| `RT_INVITE_ONLY` | `1` to test invites and the waitlist, `0` to let anyone sign up |
| `ANTHROPIC_API_KEY` | optional: leave empty to run rules-only (see section 10) |

Load `.env` into this terminal (do this again in any new backend terminal), then build
the schema:

```bash
set -a && source .env && set +a
.venv/bin/alembic upgrade head
```

It prints little or nothing when it works. Check where the schema is:

```bash
.venv/bin/alembic current
```

It should print `0016_admin_ops (head)`.

## 4. Publish the consent notices

Sign-up asks people to accept the Terms (`service`) and confirm they're 18 or older
(`age_18_plus`); the waitlist and the optional research consent have notices too. The
app refuses to sign anyone up until those notices exist. Publish a local version of each
(the file is the exact text people agree to; for local testing any text will do):

```bash
printf "Local test notice. Not the real terms.\n" > /tmp/rt-notice.txt
for purpose in service age_18_plus waitlist research; do
  .venv/bin/python -m app.auth.cli publish-notice "$purpose" local-v1 "/legal/terms" --body-file /tmp/rt-notice.txt
done
```

Each line prints `published <purpose> local-v1 (en)`.

## 5. Make an invite code (invite-only mode)

Skip this if you set `RT_INVITE_ONLY=0`.

```bash
.venv/bin/python -m app.auth.cli create-invite --note "my local account"
```

It prints a code like `ABCD-EFGH-JKLM` **once**. Copy it; you'll need it in step 8.

## 6. Start the backend

Still in terminal 1 (with `.env` loaded):

```bash
.venv/bin/uvicorn app.main:app --reload --env-file .env
```

Leave it running. Check it in a browser or another terminal:

```bash
curl -s http://localhost:8000/health
```

You should see `{"status":"ok","llm_configured":false}` (`true` if you set a Claude key).

## 7. Set up and start the frontend

**Terminal 2:**

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

The defaults in `.env.local` are right for local use (the frontend proxies `/api/*` to
`http://localhost:8000`). When it prints `Ready`, open **http://localhost:3000**.

> Use `http://localhost:3000`. Sign-in cookies and the CSRF check are tied to
> `RT_PUBLIC_URL`, and Next's dev server blocks its scripts for other hostnames, so in
> development a visit to `127.0.0.1` is forwarded to `localhost` automatically.

## 8. Create your account

1. On http://localhost:3000 click **Sign up** (or go to `/signup`).
2. Enter any email address (it never leaves your machine), for example
   `me@example.com`, and click **Email me a sign-in link**.
3. Get the link from the dev outbox. In a third terminal, from the repository root:

   ```bash
   grep -ho "http://localhost:3000/auth/email#token=[^ \"<]*" "$(ls -t backend/.dev-outbox/* | head -1)"
   ```

   Open the printed link **in the same browser**. It works once, for 15 minutes.
4. Enter the invite code from step 5 (only in invite-only mode).
5. Tick the 18+ box and accept the terms. You land on the welcome screen, then your
   dashboard at `/app/dashboard`.

## 9. Make yourself a superadmin

The admin dashboard is for staff only. Promote the account you just made (from
`backend/`, with `.env` loaded):

```bash
ADMIN_BOOTSTRAP_EMAIL=me@example.com .venv/bin/python -m app.auth.cli bootstrap-admin
```

It prints `promoted to superadmin`. Reload the browser: the avatar menu now has
**Admin**, or go straight to **http://localhost:3000/admin**.

> **Superadmin changes ask you to sign in again.** Changing settings, roles, budgets or
> models needs a sign-in from the last 10 minutes. If you're sent to the sign-in page,
> request a new link (step 8.3) and you'll come back where you were.

To test the other roles, sign up a second account (a new invite code, a different email)
and set its role from **Admin → Settings → Staff → Add staff by email**.

---

## 10. What to try

Each box is one thing to check. Rules-only mode (no Claude key) works for all of them.

### The tailoring workspace

- [ ] **Tailor** (`/app/tailor`): click **Use the sample resume and JD**, then go through
      Analysis → Review → Score → Mentor → Export. Every rewritten bullet cites its source;
      approve or reject each one.
- [ ] Upload your own resume (PDF, DOCX or TXT) and paste a job description.
- [ ] **Download** the tailored resume. A clean download costs a credit. You start with
      none, so first give yourself some: **Admin → Users → your account → Adjust credits**
      (enter `5` and a reason). Then download DOCX or PDF.
- [ ] Free tailorings run out after the monthly allowance (2 by default): the pricing
      dialog appears.

### The user area

- [ ] **Dashboard**: recent tailorings, plan and credits, invite progress, mentor tip.
- [ ] **My resumes**: saved base resumes and their versions; set a default.
- [ ] **Profile**: Personal (name, phone, avatar upload), Job preferences, Resume details,
      Privacy (export your data as JSON, delete the account).
- [ ] **Downloads**: history; re-download inside the free window; delete one.
- [ ] **Invites & referrals**: send an invite by email (it lands in `backend/.dev-outbox/`),
      copy your referral link, revoke an unused invite. You can send 10 in total.
- [ ] **Support**: send a message; pick "A tailored line says something untrue" as the topic to see it
      appear on the admin Quality page.
- [ ] **Plan & billing**: the plan and ledger (buying needs Dodo, see section 11).
- [ ] Light and dark mode (the toggle in the header), and the layout at phone width.

### The admin dashboard (`/admin`)

- [ ] **Overview**: user counts, active users, tailorings, open tickets, revenue and Claude
      cost, sign-ups and money by day, the funnel, **Export daily CSV**. Money figures need
      the rollup job: run it once (section 12) and reload.
- [ ] **Users**: search, filter, sort, export CSV; open a user to see their history
      (metadata only, never resume text); suspend, sign out, adjust credits, grant a pass.
      Each action asks for a reason.
- [ ] **Invites**: generate codes (shown once), revoke or extend, the waitlist (approve
      sends an invite email to the outbox), the invite funnel.
- [ ] **Referrals**: the review queue and the referral rules.
- [ ] **Support**: the inbox; reply (emails the user via the outbox), internal notes,
      assign, close.
- [ ] **Revenue**: totals, trend, payments list (empty without Dodo).
- [ ] **Costs**: budget meters, the kill switch, **Pause analyses now**. While paused,
      starting a tailoring in the workspace says analyses are paused; resume it again.
- [ ] **Quality**: verifier counts, parse failures (try uploading an unsupported file such
      as a `.png` in the workspace; counts appear within a minute), fabrication reports.
- [ ] **Integrations**: status cards; **Run health check** on Database; models per step;
      the webhook log. Secrets show only "set" or "not set".
- [ ] **Settings**: flip a flag (for example set a **Maintenance banner** and see it on
      every page, then clear it), the plans view, staff roles, the audit log with filters:
      every change you made above is there.
- [ ] Sign in as a **support** account: Users and Support only; Billing, Costs and
      Settings are hidden, and their API calls answer 403.
- [ ] Sign in as a plain user and open `/admin`: you get a 404.

## 11. Optional extras

**Claude.** Put `ANTHROPIC_API_KEY` in `backend/.env` and restart the backend. Claude
then reviews unclear gaps, rewrites bullets, judges semantic relevance and polishes the
mentor's wording; everything still goes through the verifier. Each account gets 10 Claude
analyses a day by default; later ones run rules-only. Spend shows on **Admin → Costs**.

**Payments (Dodo test mode).** Follow "Run it locally in test mode" in the
[README](../README.md#run-it-locally-in-test-mode): test products, the webhook relay, and
test cards such as `4242 4242 4242 4242`.

**Google and GitHub sign-in.** Create OAuth apps, register the redirect URIs
`http://localhost:3000/api/auth/google/callback` and
`http://localhost:3000/api/auth/github/callback`, and put the client ids and secrets in
`backend/.env`. Without them the buttons say the provider is unavailable.

## 12. Scheduled jobs (run them by hand)

In production these run from cron ([admin.md section 9](admin.md#9-scheduled-jobs)).
Locally, run them when you want their effect (from `backend/`, with `.env` loaded):

```bash
.venv/bin/python -m app.billing.cli refresh-aggregates --days 90   # fills Revenue, Costs and the Overview's money
.venv/bin/python -m app.billing.cli budget-check                   # budget alerts (to the outbox, and Slack if set)
.venv/bin/python -m app.auth.cli expire-invites                    # frees slots of expired, unused invites
.venv/bin/python -m app.billing.cli purge-expired                  # retention purge of old resume text
```

## 13. Automated tests

**Backend** (needs Postgres; it creates and drops throwaway databases):

```bash
cd backend && .venv/bin/pytest -q
```

**Frontend unit tests and type check:**

```bash
cd frontend && npx tsc --noEmit -p . && npx vitest run
```

**End-to-end** (a real browser against both servers). Install the browser once, then run.
Stop your own `npm run dev` first (Next allows one dev server per folder):

```bash
cd frontend && export PLAYWRIGHT_BROWSERS_PATH="$HOME/.playwright-browsers" && npx playwright install chromium
```

```bash
cd frontend && PLAYWRIGHT_BROWSERS_PATH="$HOME/.playwright-browsers" npm run test:e2e
```

If ports 3000 or 8000 are taken by something else, run the suite on other ports (use
`localhost`, never `127.0.0.1`):

```bash
cd frontend && E2E_WEB_URL=http://localhost:3100 E2E_API_URL=http://localhost:8100 PLAYWRIGHT_BROWSERS_PATH="$HOME/.playwright-browsers" npm run test:e2e
```

More on the test suites: [testing.md](testing.md).

## 14. Troubleshooting

| What you see | Why | Fix |
|---|---|---|
| `connection refused` / `database "resume_tailor" does not exist` | Postgres isn't running, or step 2 was skipped | `brew services start postgresql@16`, then `createdb resume_tailor` |
| Sign-up stops at the consent step ("Our terms were just updated", `stale_notice`) | No consent notices published | Step 4 |
| No email arrives | Emails are files, not real mail | Step 8.3: read `backend/.dev-outbox/` |
| The magic link says expired or used | Links work once, for 15 minutes, in the browser that asked | Request a new one |
| "Too many requests" when signing in | 5 magic links per 15 minutes per IP | Wait, or set `RT_DEV_RATE_LIMIT_SCALE=10` in `backend/.env` and restart |
| Buttons stay grey, pages never become interactive | The page was opened on a host other than `localhost` (`127.0.0.1` forwards by itself; a LAN IP or custom hostname doesn't), or a code from before this fix is running | Use `http://localhost:3000` |
| The email button is grey on the sign-in page | It waits for an address with an `@` | Type your email |
| Google and GitHub buttons say "Provider unavailable" | No OAuth keys in `backend/.env` | Expected locally; see section 11 |
| Signed in but every action fails with a CSRF error | The browser origin doesn't match `RT_PUBLIC_URL` | Keep both at `http://localhost:3000` |
| `/admin` shows 404 | The account isn't staff | Step 9, then reload |
| Sent to sign in when saving a setting | Superadmin step-up (sign-in older than 10 minutes) | Sign in again; you return to the page |
| Revenue, Costs or the Overview show no money | The rollup job hasn't run | Section 12: `refresh-aggregates` |
| `Another next dev server is already running` | A dev server is already running in `frontend/` | Stop it (Ctrl+C in its terminal), or use that one |
| `Address already in use` on 8000 or 3000 | Another app holds the port | `lsof -iTCP:8000 -sTCP:LISTEN` to find it; stop it, or run on other ports (section 13) |
| Backend starts but `llm_configured` is false | No Claude key | Fine: everything works rules-only. Add the key for Claude (section 11) |
| `alembic current` isn't at `0016_admin_ops` after pulling new code | New migrations | `.venv/bin/alembic upgrade head` |

## 15. Start over

To wipe all local data and begin again (this deletes every local account and tailoring):

```bash
dropdb resume_tailor && createdb resume_tailor
```

Then repeat from step 3's `alembic upgrade head`, followed by steps 4, 5 and 8.
