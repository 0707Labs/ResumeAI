"""Row-level security behind a transaction pooler.

A transaction pooler (PgBouncer pool_mode=transaction) hands each transaction whichever
server connection is free, so anything a request sets at session level follows that
connection into someone else's request. app/db/rls.py keeps the rt_app role and
app.user_id transaction-local (SET LOCAL ROLE, set_config(..., true)); these tests check
that they never outlive a request.

Every request here shares one server connection: the app's engine keeps a single pooled
connection, and the "pgbouncer" case also goes through a real PgBouncer in transaction
mode with one server connection (RT_TEST_PGBOUNCER_URL, set in CI). Between signed-in
requests, an anonymous request on that same connection must run as the login role with
no app.user_id."""

import os
from contextlib import suppress

import pytest
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.deps import current_user
from app.db.rls import service_scope
from app.db.session import get_db
from tests.conftest import ORIGIN
from tests.test_admin_security import make_user

# e.g. postgresql+psycopg://postgres:postgres@localhost:6432/ (the database is filled in).
PGBOUNCER_URL = os.environ.get("RT_TEST_PGBOUNCER_URL", "")
PROBE = text("SELECT current_user, session_user, current_setting('app.user_id', true), pg_backend_pid()")


async def probe(db: AsyncSession) -> dict:
    role, login, user_id, pid = (await db.execute(PROBE)).one()
    return {"role": role, "login": login, "user_id": user_id or None, "pid": pid}


@pytest.fixture(params=["direct", "pgbouncer"])
def pooled_url(request, pg_url) -> str:
    if request.param == "direct":
        return pg_url
    if not PGBOUNCER_URL:
        if os.environ.get("CI"):
            pytest.fail("CI must set RT_TEST_PGBOUNCER_URL")
        pytest.skip("RT_TEST_PGBOUNCER_URL not set (a PgBouncer in pool_mode=transaction)")
    database = make_url(pg_url).database
    return make_url(PGBOUNCER_URL).set(database=database).render_as_string(hide_password=False)


@pytest.fixture
def pooled_client(api_app, pooled_url):
    """The app with one pooled DB connection for every request, plus probe routes."""
    engine = create_async_engine(pooled_url, pool_size=1, max_overflow=0, pool_timeout=5)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def pooled_db():
        async with sessions() as s:
            yield s

    api_app.dependency_overrides[get_db] = pooled_db

    @api_app.get("/test/pool/anonymous")
    async def anonymous(db: AsyncSession = Depends(get_db)) -> dict:
        return await probe(db)

    @api_app.get("/test/pool/me")
    async def me(_=Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
        seen = await probe(db) | {"users": (await db.execute(text("SELECT count(*) FROM users"))).scalar_one()}
        await db.commit()
        async with service_scope(db):
            seen["service"] = await probe(db)
            await db.commit()
        seen["after"] = await probe(db)
        return seen

    @api_app.get("/test/pool/fails")
    async def fails(_=Depends(current_user), db: AsyncSession = Depends(get_db)) -> None:
        with suppress(DBAPIError):
            await db.execute(text("SELECT 1 / 0"))  # aborts the transaction while running as rt_app
        raise HTTPException(409)

    # One client, so one event loop for the pooled connection; users switch by signing in again.
    with TestClient(api_app, headers={"Origin": ORIGIN}) as client:
        yield client
        client.portal.call(engine.dispose)


def test_role_and_user_id_never_outlive_a_request(pooled_client, pg_engine):
    a, b = make_user(pg_engine, "a@example.com"), make_user(pg_engine, "b@example.com")
    clean = pooled_client.get("/test/pool/anonymous").json()
    assert clean["role"] == clean["login"] != "rt_app" and clean["user_id"] is None
    pids = {clean["pid"]}

    for user in (a, b, a):
        assert pooled_client.post(f"/test/login/{user}").status_code == 200
        me = pooled_client.get("/test/pool/me").json()
        assert (me["role"], me["user_id"], me["users"]) == ("rt_app", str(user), 1)
        assert (me["service"]["role"], me["service"]["user_id"]) == (clean["role"], None)
        assert (me["after"]["role"], me["after"]["user_id"]) == ("rt_app", str(user))

        nobody = pooled_client.get("/test/pool/anonymous").json()
        assert (nobody["role"], nobody["user_id"]) == (clean["role"], None)
        pids |= {me["pid"], me["service"]["pid"], me["after"]["pid"], nobody["pid"]}

    # A request that fails mid-transaction as rt_app leaves nothing behind either.
    assert pooled_client.get("/test/pool/fails").status_code == 409
    nobody = pooled_client.get("/test/pool/anonymous").json()
    assert (nobody["role"], nobody["user_id"]) == (clean["role"], None)
    pids.add(nobody["pid"])

    assert len(pids) == 1, "every request should have reused the one server connection"
