# Deploying Resume Tailor

How the backend and frontend run outside a laptop: the database, how the frontend reaches
the backend on one app domain, the Railway services, email, optional error reporting, and
how to release to staging, then production, and roll back.

Placeholders: `<app-domain>` is the product's domain (not chosen yet), `<api-staging>` and
`<api-production>` are the `api` service's Railway domains (`*.up.railway.app`, or a custom
`api.` subdomain).

## Database connections

The backend needs two URLs. Both connect as **the same login role**; only the host and
port differ.

| Variable | Used by | Connects to |
|---|---|---|
| `RT_DATABASE_URL` | the API, scheduled jobs, the admin CLIs (`app.auth.cli`, `app.billing.cli`) | the pooler (PgBouncer, `pool_mode = transaction`), or Postgres directly when there is no pooler |
| `RT_MIGRATION_DATABASE_URL` | the pre-deploy step (`python -m app.migrate`, which runs `alembic upgrade head`) and any manual `alembic` command | Postgres directly, never a transaction pooler |

Alembic uses `RT_MIGRATION_DATABASE_URL` when it is set, else `RT_DATABASE_URL`
(`backend/alembic/env.py`). The app itself never reads `RT_MIGRATION_DATABASE_URL`.

### URL format

```
postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE
```

- The scheme must be `postgresql+psycopg` (psycopg 3). A plain `postgresql://` URL makes
  SQLAlchemy load psycopg2, which isn't installed, so the app fails on its first query.
  Hosting providers (Railway included) hand out `postgresql://` URLs, so build ours from the
  parts instead of copying theirs.
- Percent-encode the password if it has `@`, `:`, `/` or `%`.
- Add `?sslmode=require` when the connection leaves a private network (a public proxy
  host). Traffic on a provider's private network doesn't need it.

Examples, with `rt_owner` as the login role:

```bash
# Runtime, through PgBouncer in transaction mode
RT_DATABASE_URL=postgresql+psycopg://rt_owner:PASSWORD@pgbouncer.internal:6432/resume_tailor
# Migrations, straight to Postgres
RT_MIGRATION_DATABASE_URL=postgresql+psycopg://rt_owner:PASSWORD@postgres.internal:5432/resume_tailor
```

With no pooler, set `RT_DATABASE_URL` to the direct URL and leave
`RT_MIGRATION_DATABASE_URL` unset.

### Why the same role

The login role owns the tables and is the *service role*. Migration `0010` runs
`GRANT rt_app TO CURRENT_USER`, which lets that role `SET ROLE rt_app` for signed-in
requests (docs/admin.md, "Row-level security"). If migrations ran as a different user
(say an admin `postgres`), it would own the tables and hold the `rt_app` grant, and the
runtime role would have neither. `rt_app` itself is `NOLOGIN` and never appears in a URL.

On a managed database where the migrating role can't `CREATE ROLE`, create `rt_app` once
as an admin first (docs/admin.md, "Setup").

### Why migrations go direct

- Poolers enforce timeouts (`query_timeout`, `idle_transaction_timeout`) that can kill a
  long migration halfway. Each Alembic run is one transaction, so it then rolls back cleanly,
  but the deploy fails.
- Some DDL can't run inside a transaction or needs session state, e.g. `CREATE INDEX
  CONCURRENTLY` or a session-level `SET`. Future migrations may need them.
- With one direct connection, a failed migration is easy to read: no pooler errors mixed in.

### Running the API behind a transaction pooler

A transaction pooler gives each transaction whichever server connection is free. Anything
a request sets at *session* level would follow that connection into someone else's
request. The app is safe for this:

- Row-level security state is transaction-local. `app/db/rls.py` runs
  `SET LOCAL ROLE rt_app` and `set_config('app.user_id', ..., true)` at the start of
  every transaction of a signed-in request, and `service_scope` steps out with
  `RESET ROLE` inside the transaction. Postgres drops all of it at commit or rollback.
- `backend/tests/test_rls_pooling.py` checks this. Every request shares one server
  connection, users A, B and A sign in in turn, and an anonymous request runs between each.
  The anonymous request must run as the login role with no `app.user_id`, including after a
  request that failed mid-transaction as `rt_app`. It runs twice: through SQLAlchemy's pool
  directly, and through PgBouncer 1.26 in transaction mode with one server connection (CI's
  `backend` job; set `RT_TEST_PGBOUNCER_URL` to run that case locally).
- The code has no other session-level state: no session advisory locks, `LISTEN`, temp
  tables or `SET` without `LOCAL`. Keep it that way: use `SET LOCAL`,
  `set_config(..., true)` and `pg_advisory_xact_lock`.

PgBouncer settings that matter:

| Setting | Value | Why |
|---|---|---|
| `pool_mode` | `transaction` | Session mode works too, but doesn't share connections. |
| `max_prepared_statements` | `200` (PgBouncer 1.21+) | psycopg 3 prepares a query on the server after 5 runs. Without this, the next transaction may land on a connection without it: `prepared statement "_pg3_0" does not exist`. |
| `auth_type` | `scram-sha-256` | Matches Postgres 15's default password hashing. |
| `default_pool_size` | sized to Postgres | Postgres allows 100 connections by default. Each API process keeps its own SQLAlchemy pools, which the pooler multiplexes: the request engine (5, plus up to 10 overflow) and the LLM cost recorder's (`app/billing/costs.py`: 2, plus up to 10). |

`server_reset_query` (`DISCARD ALL`) doesn't run in transaction mode, so nothing may
depend on it.

**Do we need a pooler?** Not at first. One API process holds at most 27 connections (usually
a handful), plus one or two per scheduled job. Add PgBouncer when the instance count grows near Postgres's
connection limit. Neither URL in the app changes when you do; only the host and port in
`RT_DATABASE_URL` do.

### Local and CI

| Where | `RT_DATABASE_URL` | Migrations |
|---|---|---|
| Laptop | default `postgresql+psycopg:///resume_tailor` (local socket, your OS user) | same URL |
| pytest | a throwaway `rt_test_*` database via `RT_TEST_ADMIN_DATABASE_URL` | the fixture runs Alembic itself |
| CI (`.github/workflows/ci.yml`) | `postgres:postgres@localhost:5432/resume_tailor` (Postgres 15 service); PgBouncer on `localhost:6432` for the pooling test | same URL |

## Frontend to backend: `BACKEND_URL`

The browser only ever talks to the frontend's origin (the app domain). The Next.js server
forwards `/api/*` and `/health` to FastAPI (the rewrites in `frontend/next.config.ts`), and
server-rendered pages read from FastAPI directly (`lib/site.ts`, `lib/session.ts`). All three
take the backend's address from `BACKEND_URL` (`frontend/lib/backend.ts`).

- **Set it at build time too.** Next fixes rewrites when it builds (they're written into
  `.next/routes-manifest.json`). Tested: a build made with `BACKEND_URL=http://127.0.0.1:18182`
  and started with `BACKEND_URL=http://127.0.0.1:18181` still proxied `/health` and `/api/*`
  to `:18182`, while `lib/site.ts`/`lib/session.ts` read the runtime value. Use the same value
  for both. On Railway, service variables are available to the build, so setting it once on the
  frontend service covers both.
- **Production refuses to guess.** `next build` and `next start` fail with "BACKEND_URL must be
  set" when it's missing. Outside production it defaults to `http://localhost:8000`.
- **Origin only:** `http(s)://host[:port]`, no path. A trailing slash is fine.
- **Old name:** `RT_BACKEND_URL` still works; `BACKEND_URL` wins if both are set.
- **Use the private address.** On Railway the backend is reachable from the frontend at
  `http://<backend-service-name>.railway.internal:<port>` on the private network. That traffic
  never leaves Railway, needs no TLS, and the backend's public domain is then used only by Dodo
  webhooks (and `/health` checks). The private network isn't reachable during the build. That's
  fine: the rewrite only stores the string, and the landing page's build-time fetch falls back to
  safe defaults (invite-only, no prices) and refreshes within 60 s at runtime.

| Environment | Frontend `BACKEND_URL` (build and runtime) | Backend `RT_PUBLIC_URL` = the app domain | Backend `CORS_ORIGINS` |
|---|---|---|---|
| Local | unset (`http://localhost:8000`) | unset (`http://localhost:3000`) | unset |
| CI | `http://localhost:8000` (`next build`); Playwright sets its own | unset | unset |
| Staging | `http://api.railway.internal:8000` (staging environment) | `https://staging.<app-domain>` | `https://staging.<app-domain>` |
| Production | `http://api.railway.internal:8000` (production environment) | `https://<app-domain>` | `https://<app-domain>` |

`api` is the backend service's name and `8000` the port it listens on (set `PORT=8000` on
the service so the address stays fixed). Each Railway environment has its own private network,
so the same hostname reaches staging's backend from staging and production's from production.
`<app-domain>` is a placeholder until the domains are chosen. Whatever it becomes, `RT_PUBLIC_URL`
must match the browser's origin exactly: scheme, host (including or excluding `www.`
consistently), no path, no trailing slash.

### Everything the browser sees is on the app domain

The backend builds every URL and cookie from `RT_PUBLIC_URL`. It never uses the request's
`Host` (which, behind the proxy, is the backend's private host) or `X-Forwarded-Host`.
`backend/tests/test_app_domain.py` checks this with requests that arrive as they do in
production: `Host: backend.internal:8000`, `X-Forwarded-Host: evil.example`, and
`RT_PUBLIC_URL=https://app.example.com`.

| What | How it's built | Checked by |
|---|---|---|
| Session, CSRF, OAuth-flow and pending-sign-up cookies | `__Host-` names over https: `Secure`, `Path=/`, no `Domain`, so they're host-only on the app domain the browser called. `SameSite=Lax`. | `test_cookies_are_host_only_on_the_app_domain`, `test_oauth_redirect_uri_is_on_the_app_domain` |
| CSRF | `Origin` (or `Referer`) must equal `RT_PUBLIC_URL` exactly, plus the double-submit token. The backend's own origin, http, and other hosts get 403. | `test_csrf_accepts_only_the_app_origin` |
| OAuth callbacks | `redirect_uri` = `RT_PUBLIC_URL/api/auth/{google,github}/callback`, which the rewrite carries to the backend. After the callback, redirects are relative paths. | `test_oauth_redirect_uri_is_on_the_app_domain` |
| Magic links | `RT_PUBLIC_URL/auth/email#token=…` | `test_magic_link_is_on_the_app_domain` |
| Other links | Referral and invite links, Dodo checkout return and customer-portal return, support and budget-alert emails: all `RT_PUBLIC_URL/…` | by construction (`grep -rn public_url backend/app`) |

OAuth redirect URIs to register, per environment, in the Google and GitHub apps:

```
https://staging.<app-domain>/api/auth/google/callback
https://staging.<app-domain>/api/auth/github/callback
https://<app-domain>/api/auth/google/callback
https://<app-domain>/api/auth/github/callback
```

GitHub OAuth apps allow one callback URL each, so staging and production need separate GitHub
apps (or a single app whose callback is the production one, leaving staging on Google and
magic links).

### Client IPs behind the proxy

Rate limits and the audit log key on the visitor's address. Behind the proxy the connection
comes from the Next.js server, so the address has to come from `X-Forwarded-For`. Next passes
that header through unchanged and adds nothing (checked with `next start`); Railway's edge adds
the visitor's address. `python -m app.serve` (the image's command) therefore trusts the header
only from private and loopback addresses, plain and IPv4-mapped (`::ffff:10.0.0.0/104`), and
uvicorn takes the rightmost address that isn't trusted. A visitor can't connect from a private
address, so a forged header sent to the backend's public domain is ignored, and a forged
address in front of the edge's is skipped. `backend/tests/test_serve.py` runs uvicorn's own
middleware with these settings. `FORWARDED_ALLOW_IPS` replaces the list if ever needed.

**Check it in staging** (Railway's edge behaviour is the one thing tests can't show). Open the
staging site, then look at the `api` service's logs: each access line starts with the client
address and should be your public IP (`curl https://api.ipify.org`). Then send
`curl -H "X-Forwarded-For: 198.51.100.1" https://staging.<app-domain>/health`: the log must
still show your address, not `198.51.100.1`. If it shows a private `10.x`/`fd..` address for
every request, the edge isn't adding `X-Forwarded-For` and the trust list needs revisiting.

## Railway

One Railway project with two environments, `staging` and `production`, each with the same
services. Everything is built from this repository with the Dockerfiles; nothing is built by
Nixpacks or Railpack.

| Service | Root directory | Config file (absolute path) | What runs |
|---|---|---|---|
| `api` | `/backend` | `/backend/railway.json` | `python -m app.serve`; pre-deploy `python -m app.migrate`; health check `/health` |
| `web` | `/frontend` | `/frontend/railway.json` | `node server.js` (Next standalone); health check `/robots.txt` |
| `cron-refresh-aggregates` | `/backend` | `/backend/railway/cron-refresh-aggregates.json` | `python -m app.billing.cli refresh-aggregates`, `*/15 * * * *` |
| `cron-budget-check` | `/backend` | `/backend/railway/cron-budget-check.json` | `python -m app.billing.cli budget-check`, `*/5 * * * *` |
| `cron-purge-expired` | `/backend` | `/backend/railway/cron-purge-expired.json` | `python -m app.billing.cli purge-expired`, `15 3 * * *` (08:45 IST) |
| `cron-expire-invites` | `/backend` | `/backend/railway/cron-expire-invites.json` | `python -m app.auth.cli expire-invites`, `30 3 * * *` (09:00 IST) |
| `Postgres` | Railway's Postgres template (15 or later) | | |

- **Config files don't follow the root directory**: set each service's config-file path to the
  absolute path above (Settings, "Config-as-code"). Settings in the file override the dashboard.
- **Images.** `backend/Dockerfile` is two stages (dependencies, then a slim runtime) and runs as
  uid 10001 with a read-only app directory; `frontend/Dockerfile` builds Next's standalone server
  and runs as `node`. Both listen on `$PORT`. CI's `docker` job builds both, runs the migrations
  and all four cron commands in the API image against Postgres, checks `/health` over IPv4 and
  IPv6, and checks that the web image proxies `/health` to the API.
- **Cron services** reuse the API image with a different start command and no health check.
  Railway runs them on UTC, at most every 5 minutes, and skips a run while the previous one is
  still going. Each command exits when done (`restartPolicyType: NEVER`; the next tick is the
  retry). All four are safe to run twice.
- **Migrations** run only in the `api` service's pre-deploy step (`python -m app.migrate`),
  with `RT_MIGRATION_DATABASE_URL` when there's a pooler. A failed migration fails the deploy
  and the old version keeps serving. When the database is already ahead of the code being
  deployed (a rollback), the step says so and exits 0 instead of failing the way plain
  `alembic upgrade head` does ("Can't locate revision"); `tests/test_migrate.py`. The `web` and cron services deploy independently and may run
  against the new schema with old code for a few minutes, so migrations must stay additive (add
  columns and tables; drop them a release later).
- **One replica, one worker** for `api`: rate limits are kept in process memory. Scaling out
  needs a shared limiter first.
- **`/health`** returns 200 when `SELECT 1` answers within 3 s, else 503
  (`{"status": "unavailable", "database": "unreachable"}`). Railway uses it to decide whether a
  new deploy goes live, so a wrong `RT_DATABASE_URL` fails the deploy instead of replacing a
  working one.
- **Ports.** Set `PORT=8000` on `api` so the private address in `BACKEND_URL` stays fixed; the
  server listens on IPv4 and IPv6 (the private network is IPv6). Railway sets `web`'s port itself.
- **Public domains.** `web` gets the app domain. `api` gets a Railway domain only for Dodo's
  webhooks (`https://<api-domain>/api/billing/webhooks/dodo`); browsers never use it.

### Variables

Use Railway's shared variables for anything several backend services need, and reference the
Postgres service's variables instead of pasting passwords.

| Variable | `api` | crons | `web` | Notes |
|---|---|---|---|---|
| `RT_DATABASE_URL` | ✓ | ✓ | | `postgresql+psycopg://…` (Database connections, above) |
| `RT_MIGRATION_DATABASE_URL` | ✓ | | | only with a pooler |
| `RT_PUBLIC_URL`, `CORS_ORIGINS` | ✓ | ✓ | | the app domain; `budget-check` puts links in alerts |
| `RT_AUTH_SECRET` | ✓ | | | `python -c "import secrets; print(secrets.token_urlsafe(48))"`, different per environment |
| `ANTHROPIC_API_KEY` (and `ANTHROPIC_WORKSPACE_ID`) | ✓ | | | |
| `DODO_API_KEY`, `DODO_WEBHOOK_SECRET`, `DODO_ENVIRONMENT`, `DODO_BUSINESS_ID` | ✓ | | | `test` in staging |
| `GOOGLE_CLIENT_ID/SECRET`, `GITHUB_CLIENT_ID/SECRET` | ✓ | | | per environment (OAuth redirect URIs, above) |
| `RT_MAILER=ses`, `RT_MAIL_FROM`, `RT_SES_REGION`, `AWS_*` | ✓ | | | docs/email.md |
| `RT_SLACK_WEBHOOK_URL` | | `budget-check` | | optional |
| `RT_INVITE_ONLY`, `RT_BILLING_PRO_ENABLED` | ✓ | | | optional |
| `SENTRY_DSN` (optional), `SENTRY_TRACES_SAMPLE_RATE` | ✓ | ✓ | | Error reporting, below |
| `PORT` | `8000` | | (Railway) | |
| `BACKEND_URL` | | | ✓ | `http://api.railway.internal:8000`; used at build and runtime |
| `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_SUPPORT_EMAIL`, `NEXT_PUBLIC_GRIEVANCE_OFFICER_*` | | | ✓ | inlined at build (Dockerfile `ARG`s) |

**Email.** The `api` service refuses to start on a non-localhost `RT_PUBLIC_URL` unless
`RT_MAILER=ses` and its settings are complete, so a deploy with mail misconfigured never goes
live. SES setup, DNS (DKIM, SPF, DMARC), leaving the sandbox and the per-environment values:
docs/email.md.

Railway passes service variables to a Dockerfile build only as declared `ARG`s; the frontend
Dockerfile declares `BACKEND_URL` and the `NEXT_PUBLIC_*` ones. Never set
`RT_DEV_RATE_LIMIT_SCALE` or `RT_TEST_*` on Railway.

## Error reporting: Sentry (optional)

Off unless `SENTRY_DSN` is set. Set it on `api` and on the cron services (one Sentry
project is enough; events carry a `component` tag of `api` or `cron`). Code:
`backend/app/observability.py`, started by `create_app` and by both CLIs.

| Variable | Default | |
|---|---|---|
| `SENTRY_DSN` | unset (off) | the project's DSN |
| `SENTRY_ENVIRONMENT` | `RAILWAY_ENVIRONMENT_NAME`, else `development` | so staging and production separate |
| `SENTRY_RELEASE` | `RAILWAY_GIT_COMMIT_SHA` | ties errors to a deploy |
| `SENTRY_TRACES_SAMPLE_RATE` | `0` (errors only) | 0–1; performance traces |

**What leaves the server.** Resumes and job descriptions are the most sensitive data we hold,
and session cookies and sign-in links are credentials, so events say *where* something failed,
never *what* anyone sent. Two layers:

1. The SDK collects nothing user-supplied: `data_collection` turns off request bodies,
   headers, cookies, query strings, user info, stack-frame variables, database query data and
   AI inputs and outputs. The last matters: the Anthropic integration would otherwise attach
   prompts, which contain resumes. Breadcrumbs are off.
2. `scrub` (before every event and transaction) rebuilds the event from an allowlist instead
   of hunting for sensitive fields, because resume text also turns up in exception messages
   (pydantic validation errors include the input), log arguments and CLI arguments
   (`create-invite --email`). An event keeps: request method and path (no query), exception
   types and stack frames (file, function, line, our source lines; no message, no
   variables), the log message template (no arguments), runtime/OS, the `component` tag,
   release and environment, and span operation, description and timing.

`backend/tests/test_observability.py` sends a request whose body, query string, headers,
cookies, exception message, pydantic error and log arguments all contain a marker, plus a CLI
crash with an email in `sys.argv`, and checks that neither the marker nor the email appears
anywhere in the captured events, while the exception type, route and failing function do.
With `scrub` disabled, those tests fail even with `data_collection` on, which is why both layers
stay.

Missing an exception message is the trade-off. When an error needs more context, add it as a
log line that follows the logging rules (ids and status codes, never content) and reproduce
locally.

**Frontend.** No browser Sentry: CLAUDE.md allows the browser to call only our own origin,
and a browser SDK would also see page content. Server-side Next errors show in the `web`
service's logs.

## URLs to register

Everything users see is on the app domain. The `api` service's own domain is used only by
Dodo's webhooks (and for checking `/health` directly).

| What | Staging | Production | Registered in |
|---|---|---|---|
| App (`web`) | `https://staging.<app-domain>` | `https://<app-domain>` | DNS → Railway `web` custom domain |
| API (`api`) | `https://<api-staging>` | `https://<api-production>` | Railway `api` → generate domain |
| Dodo webhook | `https://<api-staging>/api/billing/webhooks/dodo` (test-mode endpoint) | `https://<api-production>/api/billing/webhooks/dodo` (live-mode endpoint) | Dodo → Developer → Webhooks; events in docs/billing.md section 3 |
| Google OAuth redirect | `https://staging.<app-domain>/api/auth/google/callback` | `https://<app-domain>/api/auth/google/callback` | Google Cloud → Credentials → OAuth client → Authorized redirect URIs |
| GitHub OAuth callback | `https://staging.<app-domain>/api/auth/github/callback` | `https://<app-domain>/api/auth/github/callback` | GitHub → org settings → OAuth Apps (one app per environment: one callback URL each) |
| Magic links | `https://staging.<app-domain>/auth/email#token=…` | `https://<app-domain>/auth/email#token=…` | nothing: built from `RT_PUBLIC_URL` |
| Dodo checkout return, customer-portal return | `RT_PUBLIC_URL/…` | `RT_PUBLIC_URL/…` | nothing: sent with each checkout |

- **Why Dodo goes straight to the API.** The webhook then doesn't depend on the `web`
  service being up, there's no extra hop that could touch the body the signature covers, and
  Dodo's retries (8 over about a day) reach the service that records them. The app-domain URL
  (`https://<app-domain>/api/billing/webhooks/dodo`, through the Next proxy) also works, and is
  what `/admin` → Integrations displays because it builds the URL from `RT_PUBLIC_URL`; register
  the direct one.
- **The API domain serves the whole API**, not just the webhook. That's safe: session and
  CSRF cookies are host-only on the app domain, so browsers never send them to the API
  domain, and state-changing calls need the app's `Origin`.
- **Google:** a web-application OAuth client per environment (or one client listing both
  redirect URIs). The flow is server-side, so no JavaScript origins are needed. On the consent
  screen, add the app domain under *Authorized domains* with the privacy and terms URLs, and
  publish it ("In production") before launch: in *Testing* only listed test users can sign in.
- **GitHub:** OAuth Apps allow one callback URL, so staging and production are separate apps
  with separate `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`.

## Release checklist

Staging first, on the exact commit that will go to production. Production repeats it with live
values. Run one-off commands (notices, invites, the first superadmin) in the `api` service's
container: `railway ssh` (or the dashboard's *Copy SSH Command* on the service). Locally they
can't reach the private database. For SQL, `railway connect` opens a `psql` shell on the
Postgres service.

### Once, before the first deploy

- [ ] Domains chosen; `staging.<app-domain>` and `<app-domain>` point at Railway's `web`
      custom domains (Railway shows the CNAME; it issues the TLS certificates).
- [ ] Railway project with `staging` and `production` environments and the seven services in
      "Railway" above (root directory and config-file path set on each).
- [ ] Postgres: a login role that owns the schema instead of the template's superuser, and the
      `rt_app` role (docs/admin.md, "Row-level security"). As the `postgres` user, once per
      environment:

      ```sql
      CREATE ROLE rt_owner LOGIN PASSWORD '<generated>';
      CREATE ROLE rt_app NOLOGIN NOINHERIT;
      GRANT rt_app TO rt_owner WITH ADMIN OPTION;
      ALTER DATABASE railway OWNER TO rt_owner;   -- the template's database name
      ALTER SCHEMA public OWNER TO rt_owner;
      ```

      `WITH ADMIN OPTION` is required: migration `0010` runs `GRANT rt_app TO CURRENT_USER`,
      which Postgres refuses without it ("must have admin option on role rt_app"). Checked on
      Postgres 15: as `rt_owner`, `python -m app.migrate` reaches head, `rt_owner` owns the
      tables, and `SET LOCAL ROLE rt_app` sees no rows without `app.user_id`.

      `RT_DATABASE_URL` (and `RT_MIGRATION_DATABASE_URL`, if there's a pooler) connect as
      `rt_owner` (Database connections, above).
- [ ] Backups: Railway's backups for the Postgres volume (check the plan includes them) or a
      scheduled `pg_dump` to storage outside Railway. Restore one into a scratch database once.
- [ ] GitHub ruleset on `master`: required checks `backend`, `frontend`, `docker`,
      `secret-scan` (and `e2e` if you decide to); no direct pushes.
- [ ] Railway: `staging` deploys `master` automatically with **Wait for CI** on; `production`
      deploys the same commit by hand once staging passes.
- [ ] `check-alerts`: docs/billing.md section 4 asks for `python -m app.billing.cli
      check-alerts` at least hourly, paging someone when it exits 1. That's not one of the four
      cron services yet. Add a fifth (same pattern, `0 * * * *`), or rely on the Slack budget
      alerts and the admin dashboard.

### Staging

Infrastructure and variables

- [ ] Variables per "Railway → Variables": `RT_PUBLIC_URL` and `CORS_ORIGINS` =
      `https://staging.<app-domain>`, a new `RT_AUTH_SECRET`, `PORT=8000` on `api`,
      `BACKEND_URL=http://api.railway.internal:8000` and the `NEXT_PUBLIC_*` values on `web`.
- [ ] Payments in test mode: `DODO_ENVIRONMENT=test`, test API key, the test-mode webhook
      endpoint's secret.
- [ ] Email: `RT_MAILER=ses`, staging send-only key; the sandbox is fine (verify the testers'
      addresses; docs/email.md, "Staging").
- [ ] OAuth: the staging Google client and staging GitHub app.
- [ ] Optional: `SENTRY_DSN`.

Deploy

- [ ] `api` deploys: the pre-deploy log ends at the head revision; the deploy goes live, so
      `/health` passed. `https://<api-staging>/health` and `https://staging.<app-domain>/health`
      both say `"database": "ok"`.
- [ ] `web` and the four cron services deploy; each cron service shows its schedule.

Data

- [ ] Consent notices with the real text: `python -m app.auth.cli publish-notice PURPOSE
      VERSION URL --body-file FILE` for `service`, `age_18_plus`, `waitlist`, `research`
      (docs/local-testing.md section 4 shows the loop).
- [ ] An invite (`python -m app.auth.cli create-invite`), sign up with it, then
      `ADMIN_BOOTSTRAP_EMAIL=you@… python -m app.auth.cli bootstrap-admin` (docs/admin.md
      section 6).

Integrations

- [ ] Dodo: **Send example** on the test webhook endpoint gets 200; the "unknown payment"
      review it creates is expected (resolve it).
- [ ] Sign in with Google, with GitHub, and with a magic link (headers show SPF, DKIM and
      DMARC pass; docs/email.md section 2).
- [ ] `/admin` → Integrations: database, Claude, Dodo, email and both providers show their
      expected state.

Smoke test

- [ ] Tailor a resume end to end; `/health` shows `"llm_configured": true`.
- [ ] Hit the paywall, buy with a test card, see credits arrive (webhook), download the file.
- [ ] Client IP check (Railway → "Client IPs behind the proxy").
- [ ] Cron logs: `budget-check` within 5 minutes, `refresh-aggregates` within 15; run
      `purge-expired` and `expire-invites` once by hand in the shell.
- [ ] If Sentry is on: the first event shows route, exception type and frames, and no request
      data (Error reporting, above).
- [ ] Rollback drill: roll `api` back one deployment and forward again (Rollback, below).

### Production

- [ ] Staging passed on this commit.
- [ ] docs/billing.md section 4 (Dodo go-live: compliance OK, live products and prices, fees)
      and docs/email.md section 4 (SES production access, DMARC) are done.
- [ ] Production variables: `RT_PUBLIC_URL`/`CORS_ORIGINS` = `https://<app-domain>`, its own
      `RT_AUTH_SECRET` (never staging's), `DODO_ENVIRONMENT=live` with the live key and the
      live webhook endpoint's secret, production SES key, production Google client (consent
      screen published) and GitHub app.
- [ ] `RT_INVITE_ONLY` (and `/admin/settings` → `invite_only`) as intended for launch;
      no maintenance banner.
- [ ] Deploy `api`, then `web`, then the cron services. Check `/health` on both domains.
- [ ] Repeat the staging "Data", "Integrations" and "Smoke test" items with live values. The
      purchase is one small real payment, refunded afterwards (docs/billing.md section 4).
- [ ] Every test-mode Dodo subscription cancelled (they keep sending webhooks).

## Rollback

First find out what broke; most fixes don't touch the database.

**A deploy failed.** Nothing to undo: Railway keeps the previous deployment serving until the
new one's health check passes. The deploy log says why: the migration step's error, or the
startup refusal, which names the missing variable (mail, `BACKEND_URL`).

**Bad code is live.** In the service's *Deployments* list, use the three-dot menu on the last
good deployment and choose **Rollback**. Railway restores that deployment's image **and its
variables**, so a variable change made since (a rotated key, say) is undone too: re-apply it
afterwards. Deployments older than the plan's image retention can't be rolled back; redeploy
an older commit instead.
- `api`: the older deployment's pre-deploy step finds the database ahead of its code, prints
  "a rollback. Not migrating." and exits 0, so the rollback goes live with the newer schema.
  That works because migrations are additive.
- `web`: its `BACKEND_URL` and `NEXT_PUBLIC_*` values were fixed when that image was built.
- Cron services run their own deployment's image: roll them back separately if the bug is in a
  job.
- Then `/health` on both domains and the smoke test's sign-in and tailoring steps.

**A variable is wrong.** Change it back. Railway redeploys the service. For `web`, a change to
`BACKEND_URL` or a `NEXT_PUBLIC_*` value only takes effect after that rebuild.

**A migration is wrong.** In order of preference:
1. Roll the code back (above) and leave the schema. An additive migration does no harm.
2. Fix forward: a new migration that corrects it, deployed as usual.
3. Only if the schema itself must go back: take a backup, roll `api` back, then in its shell
   run `alembic downgrade <revision>` (connects through `RT_MIGRATION_DATABASE_URL`).
   Downgrades drop what the migration added, including rows written since.
   `tests/test_db_schema.py` checks every downgrade runs, not that it keeps your data.

**Data is damaged.** Stop writes first (below), restore the latest good backup into a new
database, point `RT_DATABASE_URL` (and `RT_MIGRATION_DATABASE_URL`) at it, redeploy `api` and
the cron services. Payments made since the backup are replayed from Dodo; see docs/billing.md
section 7, and never grant a purchase by hand while its webhook is pending.

**Payments while the API is down.** Dodo retries failed webhooks 8 times over about a day, and
deliveries are deduplicated by `webhook-id`, so once the API is back they apply exactly once.
Check `/admin/billing` → *Webhooks not yet processed* (docs/billing.md section 7).

**Without a deploy** (`/admin/settings`, superadmin): `analyses_paused` stops new tailorings,
`budget_kill_switch` stops Claude spend, `maintenance_banner` tells every visitor, and
`invite_only` closes sign-up. Each change is audited.
