"""Analyses as the unit of billing, with the download as what pays: the entitlement
order (pure and against Postgres), no overspend or double charge under concurrency, a
failed export charging nothing, the 402 path, exports built from the pinned inputs, and
the pipeline using Claude only for the caller's own analysis and pinned inputs."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import routes
from app.billing import analyses, ledger
from app.billing.analyses import NoEntitlement, UnknownAnalysis
from app.billing.config import get_billing_config
from app.billing.costs import current_analysis_id
from app.billing.entitlements import CapUsage, Snapshot, can_user_run
from app.llm.client import LLMError
from app.tailoring.tailor import _LLMTailored
from tests.conftest import fixture_text
from tests.test_auth_signin import csrf

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
P1, P2, SUB = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)


# --- can_user_run: pure -----------------------------------------------------------------------


def snap(credits=0, passes=(), pro=None, free_used=0, free_allowance=2):
    return Snapshot(credits=credits, passes=tuple(passes), pro=pro, free_used=free_used,
                    free_allowance=free_allowance, credits_per_analysis=1)


def test_order_is_pass_then_pro_then_credit_then_free():
    everything = dict(credits=5, passes=[CapUsage(P1, 0, 40)], pro=CapUsage(SUB, 0, 100))
    assert can_user_run(snap(**everything)).pays_with == "pass"
    assert can_user_run(snap(**{**everything, "passes": []})).pays_with == "pro"
    assert can_user_run(snap(credits=5)).pays_with == "credit"
    assert can_user_run(snap()).pays_with == "free"


def test_pass_at_its_cap_falls_through():
    d = can_user_run(snap(credits=2, passes=[CapUsage(P1, 40, 40), CapUsage(P2, 3, 40)]))
    assert (d.pays_with, d.pass_id, d.remaining) == ("pass", P2, 36)
    d = can_user_run(snap(credits=2, passes=[CapUsage(P1, 40, 40)], pro=CapUsage(SUB, 100, 100)))
    assert (d.pays_with, d.credits, d.remaining) == ("credit", 1, 1)


def test_free_allowance_then_no_credits():
    assert can_user_run(snap(free_used=1)).remaining == 0
    d = can_user_run(snap(free_used=2))
    assert (d.allowed, d.reason, d.pays_with) == (False, "no_credits", None)


# --- against Postgres ---------------------------------------------------------------------------


@pytest.fixture
def sessions(pg_url, pg_engine):
    engine = create_async_engine(pg_url, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE analyses, credit_transactions, passes, subscriptions, users CASCADE"))


@pytest.fixture
def config():
    return get_billing_config()


def sql(pg_engine, stmt, **params):
    with pg_engine.begin() as conn:
        return conn.execute(text(stmt), params).scalar()


async def _txn_engine(pg_engine, fn):
    engine = create_async_engine(pg_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            return await fn(db)
    finally:
        await engine.dispose()


def give_credits(pg_engine, uid, n):
    asyncio.run(_txn_engine(pg_engine, lambda db: ledger.grant(
        db, uid, n, reason="purchase", idempotency_key=f"purchase:{uuid.uuid4()}")))


def new_user(pg_engine, credits=0) -> uuid.UUID:
    uid = sql(pg_engine, "INSERT INTO users (email, email_verified_at, activated_at, age_confirmed_at,"
                         " terms_version, terms_accepted_at) VALUES (:e, now(), now(), now(), 'v1', now())"
                         " RETURNING id", e=f"{uuid.uuid4().hex[:8]}@example.com")
    if credits:
        give_credits(pg_engine, uid, credits)
    return uid


def add_pass(pg_engine, uid, cap=40, starts=NOW - timedelta(days=1), days=30, revoked=False) -> uuid.UUID:
    return sql(pg_engine, "INSERT INTO passes (user_id, product_key, reference_id, starts_at, expires_at,"
                          " analyses_cap, revoked_at) VALUES (:u, 'job_hunt_pass', :r, :s, :e, :c, :rv) RETURNING id",
               u=uid, r=str(uuid.uuid4()), s=starts, e=starts + timedelta(days=days), c=cap,
               rv=NOW if revoked else None)


def add_pro(pg_engine, uid, status="active", period_end=NOW + timedelta(days=10)) -> uuid.UUID:
    return sql(pg_engine, "INSERT INTO subscriptions (user_id, provider, provider_subscription_id, product_key,"
                          " status, current_period_end, last_event_at) VALUES (:u, 'dodo', :p, 'pro_monthly', :s,"
                          " :e, now()) RETURNING id", u=uid, p=f"sub_{uuid.uuid4().hex[:8]}", s=status, e=period_end)


def run(sessions, fn):
    async def go():
        async with sessions() as db, db.begin():
            return await fn(db)
    return asyncio.run(go())


def start(sessions, config, uid, now=NOW) -> uuid.UUID:
    started = run(sessions, lambda db: analyses.start_analysis(
        db, config, uid, resume={"name": "Ada"}, jd={"raw_text": "A job"}, idempotency_key=str(uuid.uuid4()),
        now=now))
    return started.analysis.id


def pay(sessions, config, uid, aid, now=NOW):
    return run(sessions, lambda db: analyses.pay_for_download(db, config, uid, aid, now=now))


def state(pg_engine, uid):
    balance = sql(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=uid)
    total = sql(pg_engine, "SELECT coalesce(sum(delta), 0) FROM credit_transactions WHERE user_id = :u", u=uid)
    return balance, total


def concurrently(sessions, n, fn):
    """Run fn(db, i) n times at once, each in its own session and transaction; exceptions
    are returned, not raised."""
    async def one(i):
        async with sessions() as db, db.begin():
            return await fn(db, i)

    async def race():
        return await asyncio.gather(*(one(i) for i in range(n)), return_exceptions=True)
    return asyncio.run(race())


def test_starting_is_free_and_idempotent(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    key = lambda db: analyses.start_analysis(db, config, uid, resume={"name": "Ada"}, jd={"raw_text": "A job"},  # noqa: E731
                                             idempotency_key="click-1", now=NOW)
    first, again = run(sessions, key), run(sessions, key)
    assert again.replay and again.analysis.id == first.analysis.id
    for _ in range(5):
        start(sessions, config, uid)
    assert sql(pg_engine, "SELECT count(*) FROM analyses WHERE user_id = :u AND paid_at IS NULL", u=uid) == 6
    assert state(pg_engine, uid) == (0, 0)


def test_first_download_charges_one_credit_and_re_downloads_are_free(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=3)
    aid = start(sessions, config, uid)
    first = pay(sessions, config, uid, aid)
    assert (first.decision.pays_with, first.decision.remaining) == ("credit", 2)
    assert pay(sessions, config, uid, aid).decision is None
    assert state(pg_engine, uid) == (2, 2)
    assert sql(pg_engine, "SELECT idempotency_key FROM credit_transactions WHERE reason = 'analysis_charge'"
                          " AND reference_id = :a", a=str(aid)) == f"charge:{aid}"


def test_entitlement_order_against_the_database(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=1)
    add_pass(pg_engine, uid, revoked=True)
    add_pass(pg_engine, uid, starts=NOW - timedelta(days=40))  # expired
    add_pass(pg_engine, uid, starts=NOW + timedelta(days=1))  # queued, not started
    add_pro(pg_engine, uid, status="on_hold")
    add_pro(pg_engine, uid, period_end=NOW - timedelta(days=1))
    assert pay(sessions, config, uid, start(sessions, config, uid)).analysis.entitlement == "credit"

    live = add_pass(pg_engine, uid, cap=1)
    paid = pay(sessions, config, uid, start(sessions, config, uid)).analysis
    assert (paid.entitlement, paid.pass_id) == ("pass", live)
    pro = add_pro(pg_engine, uid)
    paid = pay(sessions, config, uid, start(sessions, config, uid)).analysis  # the pass is at its cap of 1
    assert (paid.entitlement, paid.subscription_id) == ("pro", pro)
    assert state(pg_engine, uid) == (0, 0)


def test_free_downloads_are_per_calendar_month(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    last_month = NOW - timedelta(days=25)
    for _ in range(2):
        assert pay(sessions, config, uid, start(sessions, config, uid, last_month), last_month) \
            .analysis.entitlement == "free"
    for _ in range(2):
        assert pay(sessions, config, uid, start(sessions, config, uid)).analysis.entitlement == "free"
    with pytest.raises(NoEntitlement) as denied:
        pay(sessions, config, uid, start(sessions, config, uid))
    assert denied.value.decision.reason == "no_credits"


def test_someone_elses_analysis_cant_be_paid_for(sessions, config, pg_engine):
    owner, other = new_user(pg_engine), new_user(pg_engine, credits=1)
    with pytest.raises(UnknownAnalysis):
        pay(sessions, config, other, start(sessions, config, owner))
    assert state(pg_engine, other) == (1, 1)


def test_concurrent_downloads_never_overspend_credits(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=1)
    no_free = config.model_copy(update={"free": config.free.model_copy(update={"analyses_per_month": 0})})
    ids = [start(sessions, config, uid) for _ in range(10)]
    results = concurrently(sessions, 10, lambda db, i: analyses.pay_for_download(db, no_free, uid, ids[i], now=NOW))
    assert sum(isinstance(r, analyses.Payment) for r in results) == 1
    assert all(isinstance(r, analyses.Payment | NoEntitlement) for r in results)
    assert state(pg_engine, uid) == (0, 0)


def test_concurrent_downloads_of_one_analysis_charge_once(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=5)
    aid = start(sessions, config, uid)
    results = concurrently(sessions, 8, lambda db, i: analyses.pay_for_download(db, config, uid, aid, now=NOW))
    assert sum(r.decision is not None for r in results) == 1
    assert state(pg_engine, uid) == (4, 4)


def test_concurrent_downloads_never_exceed_free_downloads_or_pass_cap(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    ids = [start(sessions, config, uid) for _ in range(8)]
    results = concurrently(sessions, 8, lambda db, i: analyses.pay_for_download(db, config, uid, ids[i], now=NOW))
    assert sorted(r.analysis.entitlement for r in results if isinstance(r, analyses.Payment)) == ["free", "free"]

    other = new_user(pg_engine)
    pass_id = add_pass(pg_engine, other, cap=3)
    ids = [start(sessions, config, other) for _ in range(8)]
    results = concurrently(sessions, 8, lambda db, i: analyses.pay_for_download(db, config, other, ids[i], now=NOW))
    paid = [r.analysis for r in results if isinstance(r, analyses.Payment)]
    assert sum(a.pass_id == pass_id for a in paid) == 3
    assert sum(a.entitlement == "free" for a in paid) == 2  # then the free downloads
    assert len(paid) == 5


# --- the HTTP surface ------------------------------------------------------------------------


class FakeClaude:
    def __init__(self, fail=False):
        self.fail, self.seen = fail, []

    def parse(self, *, system, user, schema, effort="medium"):
        self.seen.append(current_analysis_id.get())
        if self.fail:
            raise LLMError("Claude API error (529).")
        if schema is _LLMTailored:
            return _LLMTailored(bullets=[])
        raise LLMError("not faked")


@pytest.fixture
def signed_in(client, pg_engine):
    uid = new_user(pg_engine)
    assert client.post(f"/test/login/{uid}").status_code == 200
    client.headers.update(csrf(client))
    return uid


@pytest.fixture
def inputs(client):
    resume = client.post("/api/resume/parse", files={"file": ("r.txt", fixture_text("resume_analyst.txt"))}).json()
    jd = client.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")}).json()
    return {"resume": resume, "jd": jd}


def begin(client, inputs) -> str:
    res = client.post("/api/analyses", json=inputs)
    assert res.status_code == 200, res.text
    return res.json()["analysis_id"]


def tailored(client, inputs, aid=None, use_llm=False) -> dict:
    headers = {"X-Analysis-Id": aid} if aid else {}
    return client.post("/api/tailor", json={**inputs, "use_llm": use_llm}, headers=headers).json()


def download(client, inputs, aid, tailoring, fmt="docx", **body):
    headers = {"X-Analysis-Id": aid} if aid else {}
    return client.post(f"/api/export/{fmt}", headers=headers, json={
        "resume": inputs["resume"], "tailored": tailoring, "jd_text": inputs["jd"]["raw_text"], **body})


def test_start_needs_sign_in(client, inputs):
    assert client.post("/api/analyses", json=inputs).status_code == 401


def test_claude_is_used_only_for_the_callers_analysis_and_pinned_inputs(client, new_browser, signed_in, inputs,
                                                                        pg_engine, monkeypatch):
    claude = FakeClaude()
    monkeypatch.setattr(routes, "get_llm", lambda: claude)
    aid = begin(client, inputs)

    stranger = new_browser()
    res = stranger.post("/api/gap/analyze", json=inputs, headers={"X-Analysis-Id": aid}).json()
    assert res["notes"] == ["Rules only (sign in and start an analysis to use Claude)."]
    other_resume = {**inputs, "resume": {**inputs["resume"], "name": "Someone Else"}}
    assert any("start an analysis" in n for n in tailored(client, other_resume, aid, use_llm=True)["notes"])
    assert claude.seen == []

    tailored(client, inputs, aid, use_llm=True)
    assert claude.seen == [uuid.UUID(aid)]  # llm_usage rows get the server-side analysis id
    assert sql(pg_engine, "SELECT llm_tailored FROM analyses WHERE id = :a", a=aid) is True
    again = tailored(client, inputs, aid, use_llm=True)  # Claude tailors once per analysis
    assert len(claude.seen) == 1 and any("start an analysis" in n for n in again["notes"])


def test_download_needs_sign_in_and_an_analysis(client, inputs, signed_in):
    tailoring = tailored(client, inputs)
    signed_out = client.__class__(client.app, headers={"Origin": "http://localhost:3000"})
    assert download(signed_out, inputs, None, tailoring).status_code == 401
    assert (res := download(client, inputs, None, tailoring)).status_code == 409
    assert res.json()["detail"] == "analysis_required"
    assert download(client, inputs, str(uuid.uuid4()), tailoring).status_code == 404


def test_rules_only_download_pays_once_then_402_when_nothing_pays(client, signed_in, inputs, pg_engine):
    give_credits(pg_engine, signed_in, 1)
    first = begin(client, inputs)
    tailoring = tailored(client, inputs, first)
    for _ in range(2):
        res = download(client, inputs, first, tailoring)
        assert res.status_code == 200 and res.content[:2] == b"PK"
    assert sql(pg_engine, "SELECT entitlement FROM analyses WHERE id = :a", a=first) == "credit"
    assert state(pg_engine, signed_in) == (0, 0)

    for _ in range(2):  # the two free downloads of the month
        aid = begin(client, inputs)
        assert download(client, inputs, aid, tailored(client, inputs, aid), fmt="pdf").status_code == 200
    aid = begin(client, inputs)
    res = download(client, inputs, aid, tailored(client, inputs, aid))
    assert (res.status_code, res.json()["detail"]) == (402, "no_credits")
    assert sql(pg_engine, "SELECT paid_at FROM analyses WHERE id = :a", a=aid) is None


def test_the_file_is_built_from_the_pinned_resume(client, signed_in, inputs):
    aid = begin(client, inputs)
    tailoring = tailored(client, inputs, aid)
    swapped = {**inputs, "resume": {**inputs["resume"], "name": "Someone Else"}}
    res = download(client, swapped, aid, tailoring)
    assert res.status_code == 200
    assert "Someone_Else" not in res.headers["content-disposition"]


def test_a_failed_export_charges_nothing_and_a_retry_charges_once(client, signed_in, inputs, pg_engine, monkeypatch):
    give_credits(pg_engine, signed_in, 1)
    aid = begin(client, inputs)
    tailoring = tailored(client, inputs, aid)
    render = routes._render

    def boom(*args):
        raise RuntimeError("renderer crashed")
    monkeypatch.setattr(routes, "_render", boom)
    with pytest.raises(RuntimeError):
        download(client, inputs, aid, tailoring)
    assert state(pg_engine, signed_in) == (1, 1)
    assert sql(pg_engine, "SELECT paid_at FROM analyses WHERE id = :a", a=aid) is None

    monkeypatch.setattr(routes, "_render", render)
    assert download(client, inputs, aid, tailoring).status_code == 200
    assert state(pg_engine, signed_in) == (0, 0)
    assert sql(pg_engine, "SELECT count(*) FROM credit_transactions WHERE reason = 'analysis_charge'") == 1
