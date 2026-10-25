# Deploying Resume Tailor

How the backend and frontend run outside a laptop. This page covers the database so far.
The rewrite target, Railway services, SES, Sentry and the release checklist come next.

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
