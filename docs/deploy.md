# Deploying Resume Tailor

How the backend and frontend run outside a laptop: the database, how the frontend reaches
the backend on one app domain, the Railway services, and email. Sentry and the release
checklist come next.

## Database connections

The backend needs two URLs. Both connect as **the same login role**; only the host and
port differ.

| Variable | Used by | Connects to |
|---|---|---|
| `RT_DATABASE_URL` | the API, scheduled jobs, the admin CLIs (`app.auth.cli`, `app.billing.cli`) | the pooler (PgBouncer, `pool_mode = transaction`), or Postgres directly when there is no pooler |
| `RT_MIGRATION_DATABASE_URL` | `alembic upgrade head` (the pre-deploy step) | Postgres directly, never a transaction pooler |

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
| `api` | `/backend` | `/backend/railway.json` | `python -m app.serve`; pre-deploy `python -m alembic upgrade head`; health check `/health` |
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
- **Migrations** run only in the `api` service's pre-deploy step, with
  `RT_MIGRATION_DATABASE_URL` when there's a pooler. A failed migration fails the deploy and the
  old version keeps serving. The `web` and cron services deploy independently and may run
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
