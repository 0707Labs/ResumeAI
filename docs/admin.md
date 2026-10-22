# Admin security

How staff access works: roles, capabilities, step-up, the audit log, row-level security,
and how to create the first superadmin. Code: `app/auth/roles.py`, `app/admin/`,
`app/db/rls.py`, `app/api/admin.py`; migration `0010_admin_security`; tests
`tests/test_admin_security.py`.

The original spec assumed Supabase (Auth, RLS, Storage, MFA). This project's auth is
FastAPI's own (opaque DB sessions, OAuth via Authlib, magic links) on plain Postgres with
Alembic migrations, so each piece below is the equivalent built on that stack.

## 1. Roles and capabilities

`users.role` is one of `user`, `support`, `admin`, `superadmin`. It is read from the
database on every request (the session lookup loads the user row); no cookie, header or
client flag can raise it.

Routes never check a role name. Each `/api/admin/*` route depends on
`require("<capability>")`, and `app/auth/roles.py` maps roles to capabilities:

| Capability | support | admin | superadmin |
|---|:-:|:-:|:-:|
| `staff.access`, `users.read`, `tickets.read`, `tickets.write` | ✓ | ✓ | ✓ |
| `audit.read`, `users.write`, `credits.adjust`, `passes.grant`, `invites.write`, `referrals.decide`, `billing.read`, `billing.write`, `costs.read`, `quality.read`, `integrations.read` | | ✓ | ✓ |
| `users.delete`, `roles.write`, `settings.write`, `secrets.hint` (step-up) | | | ✓ |

- No session: 401. Signed in without the capability, or suspended: 403 `forbidden`.
- `GET /api/me` returns `capabilities` so the UI can hide what the caller can't do. The
  API checks again on every call regardless.
- A test walks every `/api/admin` route and fails if one has no capability, if a mutation
  lacks CSRF, or if a normal user gets anything but 403 from it.

## 2. Step-up for superadmin actions

There's no MFA. Instead, step-up capabilities need a sign-in through an existing login
method in the last 10 minutes (`STEP_UP_WINDOW`). Every sign-in rotates the session and
stamps `auth_sessions.reauth_at`; linking a new login method rotates too but leaves
`reauth_at` empty, because linking proves nothing about who owns the account. Without a
fresh stamp the API answers 401 `reauth_required`, and the admin UI sends the caller
through `/signin?next=<page>&reauth=1`. Reads never need step-up.

TOTP could be added later as a second way to set `reauth_at`.

## 3. Audit log

`admin_audit_log` gets one row per staff mutation: actor, actor role, `action`
(`area.verb`, e.g. `roles.change`), target, reason, before/after summaries, a keyed hash
of the IP (we don't store raw IPs, same as consent and referrals) and the user agent.

- **Same transaction:** `app.admin.audit.record()` adds the row without committing, so
  the entry and the change commit or roll back together.
- **Append-only:** a trigger rejects UPDATE, DELETE and TRUNCATE. No foreign keys, so
  entries outlive the users and rows they describe.
- **Summaries only:** before/after carry ids, counts, amounts and flags. Keys like
  `resume`, `jd`, `tailored`, `body`, `token` or `secret` are refused, and a summary over
  2 KB is refused.
- Audited today: settings changes, role changes, the bootstrap, referral decisions,
  billing-review resolution. Every later admin mutation (credits, invites, suspensions,
  refunds...) must call `record()` too.
- Viewer: `GET /api/admin/audit` (`audit.read`), filtered by actor, action or target,
  paged newest first with `before_id`.

## 4. Row-level security

The API is the only database client. Two Postgres roles:

- **The login role** (whatever `RT_DATABASE_URL` connects as) owns the tables and is the
  *service role*. Sign-in flows, webhooks, admin routes, CLIs and scheduled jobs run as it.
- **`rt_app`** (NOLOGIN). Once `current_user` identifies a signed-in caller, the request's
  DB session runs `SET LOCAL ROLE rt_app` and sets `app.user_id`
  (`app/db/rls.py`). Both are transaction-local, so they're re-applied at the start of
  each later transaction in the request and can't leak through the connection pool.

What `rt_app` can do (`USER_TABLES` in the migration):

- Rows of user-owned tables only where the owner column equals `app_user_id()`: users,
  accounts, auth_sessions, consent_records, credit_transactions, passes, subscriptions,
  billing_customers, payments, analyses, downloads, referrals (as referrer or referee).
- No privileges at all on staff, flow, webhook or cost tables: `admin_audit_log`,
  `app_settings`, `llm_usage`, `invites`, `invite_redemptions`, `waitlist`,
  `pending_auth`, `email_tokens`, `processed_webhook_events`, `billing_reviews`.
- On `users` it may update only `name`, `credits_balance`, `referral_code` and
  `last_login_at`; never `role`, `status` or `email`.
- `current_consents` is a `security_invoker` view, so it's limited the same way.

**Stepping out on purpose.** Some signed-in work is about other users' rows: rewarding a
referrer, checking that a login identity or email isn't someone else's, deleting an
account (pending sign-ins, email tokens), checking a referral code is unique. Those
blocks run inside `async with service_scope(db):` and return to the user's scope after.
Keep them small and grep-able. Beware: under RLS an UPDATE of another user's row doesn't
fail, it matches nothing. A cross-user write that "silently did nothing" means it needs a
`service_scope`.

**Setup.** The migration creates `rt_app` if missing (`CREATE ROLE` needs CREATEROLE
once per Postgres cluster) and grants it to the login role so it can `SET ROLE`. On a
managed database where the migration user lacks CREATEROLE, create it once as an admin:

```sql
CREATE ROLE rt_app NOLOGIN NOINHERIT;
GRANT rt_app TO <app_login_role>;
```

The role must not have BYPASSRLS. Downgrading `0010` drops the grants and policies but
leaves the role (other databases on the cluster may use it).

## 5. Runtime settings

`app_settings` holds switches staff can flip without a deploy (the table in 5b). Each key is typed in
`app.admin.settings.Settings`; its default comes from env/billing.toml, so nothing
changes until someone sets a value. `PUT /api/admin/settings/{key}` (superadmin, step-up,
reason required) validates, stores and audits; `POST .../reset` returns to the default.
Prices, credit amounts and pass lengths stay in `billing.toml` (purchases snapshot them).

## 5b. What the settings change today

Staff can change these without a deploy (`/admin/settings`, superadmin with a recent
sign-in). Each defaults to env or `billing.toml` until set:

| Key | Default from | Read by |
|---|---|---|
| `invite_only` | `RT_INVITE_ONLY` | sign-up, `/api/auth/config`, the invite step |
| `invites_per_user` | `[referrals].invites_per_user` | invite quota (`/api/invites`, link sign-ups) |
| `signup_bonus_credits` | `[signup].bonus_credits` | starter credits at account creation (ledger, `signup_bonus`) |
| `referrals_enabled`, `referral_trigger`, `referral_reward_credits`, `referral_monthly_cap` | `[referrals]` | referral attribution and rewards |
| `analyses_paused` | off | `POST /api/analyses` (503 `analyses_paused`; `/admin/costs`) |
| `maintenance_banner` | none | `/api/auth/config`: shown above every page (site, workspace, admin) |
| `daily_budget_usd`, `monthly_budget_usd`, `budget_kill_switch` | `[alerts]` | Claude budgets (docs/billing.md section 12) |
| `pro_enabled` | `RT_BILLING_PRO_ENABLED` | `/api/billing/plans`, checkout |
| `free_analyses_per_month` | `[free].analyses_per_month` | starting an analysis, the allowance shown to users |
| `llm_models` | built-in (claude-opus-5-5, 16000 tokens) | the Claude client, per pipeline step, cached 30 s |

The signed-out, rules-only pipeline never reads them, so it still runs without a database.

## 6. The first superadmin

The account must exist first (sign up with an invite like anyone else), so the role
never goes to an address nobody has proven. Then:

```bash
cd backend && ADMIN_BOOTSTRAP_EMAIL=you@example.com .venv/bin/python -m app.auth.cli bootstrap-admin
```

It's idempotent, audited as the system (`roles.bootstrap`), and refuses while another
superadmin exists unless you pass `--force`. Further staff are promoted from the admin
UI (`PUT /api/admin/users/{id}/role`, superadmin with step-up): nobody can change their
own role, and the last superadmin can't be demoted.

## 7. Browser side

- `proxy.ts` sends cookieless visitors on `/admin/*` to sign-in; `app/admin/layout.tsx`
  asks the backend server-side and answers 404 to anyone without `staff.access`.
- `/admin` is `noindex` (metadata and an `X-Robots-Tag` header) and disallowed in
  `robots.txt`.
- Admin rate limits: 120 reads and 30 writes a minute per IP (`admin_read`,
  `admin_write`). The limiter is in-process: move it to Redis before running more than
  one API instance.


## 8. The admin pages

| Page | Needs | What it shows |
|---|---|---|
| `/admin` (Overview) | staff | Users (total, new, active day/week/month), waitlist, paid users, tailorings, open tickets; revenue, MRR-equivalent and credits sold/used (billing.read); Claude cost and gross margin (costs.read); sign-ups and revenue/cost by day; the funnel; daily CSV |
| `/admin/revenue`, `/admin/costs` | billing.read, costs.read | docs/billing.md section 12 |
| `/admin/quality` | quality.read | Verifier counts and rates, parse failures and warnings, ATS lift, fabrication reports |
| `/admin/integrations` | integrations.read | Status cards, health checks, models per step (superadmin edits), the webhook log and replay (billing.write) |
| `/admin/settings` | audit.read (edits: superadmin) | Flags, plans and pricing (read-only), legal versions, staff roles, the audit log |

**Definitions.** Active users are distinct accounts with a session seen in the last day,
week or month. Paid users paid at least once. MRR-equivalent is active Pro subscriptions
at Pro's USD price plus the last 30 days of one-time revenue (passes and credit packs),
net of refunds. Gross margin is (net revenue after fees - Claude cost) / net revenue
after fees, over 30 days. The funnel follows the accounts created in the range: landing
views (a separate count) -> signed up -> finished a tailoring -> downloaded -> paid.

**Counts, not content.** Quality reads counts kept on each analysis (bullets produced,
blocked, flagged; approved, rejected and approved-despite-a-warning at download) and
`daily_counters` (resume parse results by code, landing views). Counters collect in memory
and are written once a minute and at shutdown (`app.admin.counters`), so the parse path
never waits on the database. Landing views are a cookie-free beacon (`POST
/api/metrics/landing-view`): no IP, no user, a number per UTC day.

**Integrations never show secrets.** Each secret is "set" or "not set"; a superadmin also
sees the last 4 characters of values long enough for that to give nothing away, never for
URLs. Health checks run server-side against read-only endpoints (Claude's model lookup,
Dodo's product list, SES's account endpoint, the database) and store a status and a short
code (`http_401`, a class name), never a provider's message. Checks are audited
(`integrations.check`). A test sends real-looking secrets through the API and asserts no
5-character run of any of them comes back.

**Webhook replay.** While a Dodo delivery is failing, its verified event data is kept
(`processed_webhook_events.payload`) and cleared once it's processed. Replay runs it
through the same idempotent path as a live delivery, so it can never apply twice; it is
audited (`billing.webhook_replay`). The list never returns the payload.

**Models per step.** `llm_models` maps a pipeline step (gap analysis, tailor, tailor
repair, ATS semantic, mentor) to a model, max tokens and effort. Only models priced in
`billing.toml [llm_prices]` are accepted, so every call stays costed; a model that later
loses its price, a bad value or an unreadable setting falls back to the default. The
client sets effort rather than temperature.

## 9. Scheduled jobs

| Job | Schedule | Does |
|---|---|---|
| `python -m app.billing.cli purge-expired` | daily | retention purge (docs/billing.md section 11) |
| `python -m app.billing.cli refresh-aggregates` | every 15 minutes | revenue and cost rollups |
| `python -m app.billing.cli budget-check` | every 5 minutes | budget alerts |
| `python -m app.auth.cli expire-invites` | daily | revokes personal invites that expired unused, so the sender's slot comes back |

```
30 3 * * * cd /srv/resume-tailor/backend && .venv/bin/python -m app.auth.cli expire-invites
```
