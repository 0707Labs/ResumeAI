"""Tailorings ("analyses"): what allows one (pure and against Postgres), that starting never
spends a credit, no overuse of the free allowance or a cap under concurrency, release
exactly once, the 402 path, and the pipeline using Claude only for the caller's own live run."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import routes
from app.billing import analyses, ledger
from app.billing.analyses import NoEntitlement
from app.billing.config import get_billing_config
from app.billing.costs import current_analysis_id
from app.billing.entitlements import CapUsage, Snapshot, can_start_tailoring, can_user_run
from app.llm.client import LLMError
from app.tailoring.tailor import _LLMTailored
from tests.conftest import fixture_text
from tests.test_auth_signin import csrf

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
P1, P2, SUB = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)


# --- decisions: pure ------------------------------------------------------------------------------


def snap(credits=0, passes=(), pro=None, free_used=0, free_allowance=2):
    return Snapshot(credits=credits, passes=tuple(passes), pro=pro, free_used=free_used,
                    free_allowance=free_allowance, credits_per_download=1)


def test_tailoring_order_is_free_then_pass_then_pro_then_credit_balance():
    everything = dict(credits=5, passes=[CapUsage(P1, 0, 40)], pro=CapUsage(SUB, 0, 100))
    assert can_start_tailoring(snap(**everything)).pays_with == "free"
    assert can_start_tailoring(snap(**everything, free_used=2)).pays_with == "pass"
    assert can_start_tailoring(snap(**{**everything, "passes": []}, free_used=2)).pays_with == "pro"
    d = can_start_tailoring(snap(credits=5, free_used=2))
    assert (d.pays_with, d.remaining) == ("credit", 5)  # the balance is untouched


def test_pass_at_its_cap_falls_through():
    d = can_start_tailoring(snap(credits=2, free_used=2, passes=[CapUsage(P1, 40, 40), CapUsage(P2, 3, 40)]))
    assert (d.pays_with, d.pass_id, d.remaining) == ("pass", P2, 36)
    d = can_start_tailoring(snap(credits=2, free_used=2, passes=[CapUsage(P1, 40, 40)], pro=CapUsage(SUB, 100, 100)))
    assert (d.pays_with, d.remaining) == ("credit", 2)


def test_past_the_free_allowance_nothing_left_means_no_credits():
    assert can_start_tailoring(snap(free_used=1)).remaining == 0
    d = can_start_tailoring(snap(free_used=2))
    assert (d.allowed, d.reason, d.pays_with) == (False, "no_credits", None)
    assert can_start_tailoring(snap(free_used=2, free_allowance=0, credits=1)).allowed
    assert not can_start_tailoring(snap(free_allowance=0)).allowed


def test_download_needs_a_pass_pro_or_a_credit_whatever_the_free_allowance():
    assert not can_user_run(snap()).allowed  # free tailorings don't make downloads free
    assert can_user_run(snap(credits=1)).remaining == 0
    assert can_user_run(snap(passes=[CapUsage(P1, 40, 40)])).pays_with == "pass"  # caps limit tailoring only
    assert can_user_run(snap(pro=CapUsage(SUB, 0, 100))).pays_with == "pro"


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


def new_user(pg_engine, credits=0) -> uuid.UUID:
    uid = sql(pg_engine, "INSERT INTO users (email, email_verified_at, activated_at, age_confirmed_at,"
                         " terms_version, terms_accepted_at) VALUES (:e, now(), now(), now(), 'v1', now())"
                         " RETURNING id", e=f"{uuid.uuid4().hex[:8]}@example.com")
    if credits:
        asyncio.run(_txn_engine(pg_engine, lambda db: ledger.grant(
            db, uid, credits, reason="purchase", idempotency_key=f"purchase:{uid}")))
    return uid


async def _txn_engine(pg_engine, fn):
    engine = create_async_engine(pg_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            return await fn(db)
    finally:
        await engine.dispose()


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


def start(sessions, config, uid, key=None, now=NOW):
    return run(sessions, lambda db: analyses.start_analysis(db, config, uid, idempotency_key=key or str(uuid.uuid4()),
                                                            now=now))


def state(pg_engine, uid):
    balance = sql(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=uid)
    total = sql(pg_engine, "SELECT coalesce(sum(delta), 0) FROM credit_transactions WHERE user_id = :u", u=uid)
    return balance, total


def test_starting_a_tailoring_never_spends_a_credit(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=3)
    for _ in range(4):  # 2 free, then 2 backed by the balance
        start(sessions, config, uid)
    rows = sql(pg_engine, "SELECT string_agg(entitlement || ':' || billing_state || ':' || credits, ','"
                          " ORDER BY created_at, entitlement DESC) FROM analyses WHERE user_id = :u", u=uid)
    assert sorted(rows.split(",")) == ["credit:none:0"] * 2 + ["free:none:0"] * 2
    assert state(pg_engine, uid) == (3, 3)
    assert sql(pg_engine, "SELECT count(*) FROM credit_transactions WHERE reason = 'analysis_charge'") == 0


def test_same_idempotency_key_returns_the_same_analysis(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    first = start(sessions, config, uid, key="click-1")
    again = start(sessions, config, uid, key="click-1")
    assert again.replay and again.analysis.id == first.analysis.id
    assert sql(pg_engine, "SELECT count(*) FROM analyses WHERE user_id = :u", u=uid) == 1


def test_entitlement_order_against_the_database(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=1)
    no_free = config.model_copy(update={"free": config.free.model_copy(update={"analyses_per_month": 0})})
    add_pass(pg_engine, uid, revoked=True)
    add_pass(pg_engine, uid, starts=NOW - timedelta(days=40))  # expired
    add_pass(pg_engine, uid, starts=NOW + timedelta(days=1))  # queued, not started
    add_pro(pg_engine, uid, status="on_hold")
    add_pro(pg_engine, uid, period_end=NOW - timedelta(days=1))
    assert start(sessions, no_free, uid).analysis.entitlement == "credit"

    live = add_pass(pg_engine, uid, cap=1)
    a = start(sessions, no_free, uid).analysis
    assert (a.entitlement, a.pass_id) == ("pass", live)
    pro = add_pro(pg_engine, uid)
    a = start(sessions, no_free, uid).analysis  # the pass is at its cap of 1
    assert (a.entitlement, a.subscription_id) == ("pro", pro)
    assert state(pg_engine, uid) == (1, 1)


def test_free_allowance_is_per_calendar_month_and_failed_runs_dont_count(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    last_month = start(sessions, config, uid, now=NOW - timedelta(days=25)).analysis
    assert last_month.entitlement == "free"
    a = start(sessions, config, uid).analysis
    run(sessions, lambda db: analyses.release(db, a.id, uid, reason="llm_degraded", degraded=True))
    assert start(sessions, config, uid).analysis.entitlement == "free"
    assert start(sessions, config, uid).analysis.entitlement == "free"
    with pytest.raises(NoEntitlement) as denied:
        start(sessions, config, uid)
    assert denied.value.decision.reason == "no_credits"


def test_the_free_allowance_is_configurable(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    five = config.model_copy(update={"free": config.free.model_copy(update={"analyses_per_month": 5})})
    assert [start(sessions, five, uid).analysis.entitlement for _ in range(5)] == ["free"] * 5
    with pytest.raises(NoEntitlement):
        start(sessions, five, uid)


def test_concurrent_starts_never_exceed_free_allowance_or_pass_cap(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    results = concurrently(sessions, 8, lambda db: analyses.start_analysis(
        db, config, uid, idempotency_key=str(uuid.uuid4()), now=NOW))
    assert sorted(r.analysis.entitlement for r in results if isinstance(r, analyses.Started)) == ["free", "free"]

    other = new_user(pg_engine)
    pass_id = add_pass(pg_engine, other, cap=3)
    results = concurrently(sessions, 8, lambda db: analyses.start_analysis(
        db, config, other, idempotency_key=str(uuid.uuid4()), now=NOW))
    allowed = [r.analysis for r in results if isinstance(r, analyses.Started)]
    assert sum(a.entitlement == "free" for a in allowed) == 2  # the free allowance first
    assert sum(a.pass_id == pass_id for a in allowed) == 3  # then the pass, up to its cap
    assert len(allowed) == 5


def concurrently(sessions, n, fn):
    """Run fn(db) n times at once, each in its own session and transaction; exceptions
    are returned, not raised."""
    async def one():
        async with sessions() as db, db.begin():
            return await fn(db)

    async def race():
        return await asyncio.gather(*(one() for _ in range(n)), return_exceptions=True)
    return asyncio.run(race())


def legacy_credit_run(sessions, config, uid):
    """A run started before tailoring became free: a credit was reserved at start."""
    a = start(sessions, config, uid, now=NOW).analysis

    async def reserve(db):
        await ledger.charge(db, uid, 1, reason="analysis_charge", idempotency_key=f"charge:{a.id}",
                            reference_id=str(a.id))
        await db.execute(text("UPDATE analyses SET entitlement = 'credit', billing_state = 'reserved', credits = 1 WHERE id = :a"),
                         {"a": a.id})
    run(sessions, reserve)
    return a


def test_release_happens_exactly_once_and_refunds_a_legacy_credit_once(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=2)
    a = legacy_credit_run(sessions, config, uid)
    assert state(pg_engine, uid) == (1, 1)

    # Request-handler failures and the abandoned-run sweep race to release it; one wins.
    ops = iter([lambda db: analyses.release(db, a.id, uid, reason="error")] * 6
               + [lambda db: analyses.sweep(db, now=NOW + timedelta(days=2))] * 2)
    attempts = concurrently(sessions, 8, lambda db: next(ops)(db))
    assert [r == 1 for r in attempts].count(True) == 1, attempts
    assert run(sessions, lambda db: analyses.sweep(db, now=NOW + timedelta(days=2))) == 0
    assert state(pg_engine, uid) == (2, 2)
    assert sql(pg_engine, "SELECT count(*) FROM credit_transactions WHERE reason = 'refund'") == 1
    assert sql(pg_engine, "SELECT billing_state || '/' || status FROM analyses WHERE id = :a", a=a.id) \
        == "refunded/failed"


def test_finish_counts_the_run_and_a_late_failure_changes_nothing(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=1)
    a = start(sessions, config, uid).analysis
    assert run(sessions, lambda db: analyses.finish(db, a.id, uid)) is True
    assert run(sessions, lambda db: analyses.release(db, a.id, uid, reason="error")) is False
    assert state(pg_engine, uid) == (1, 1)
    assert sql(pg_engine, "SELECT status FROM analyses WHERE id = :a", a=a.id) == "succeeded"


def test_abandoned_runs_are_released_by_the_sweep_or_the_next_start(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    a = start(sessions, config, uid).analysis
    start(sessions, config, uid)
    later = NOW + timedelta(hours=config.analyses.usable_hours, minutes=1)
    assert run(sessions, lambda db: analyses.sweep(db, now=later)) == 2
    assert run(sessions, lambda db: analyses.finish(db, a.id, uid)) is False  # too late to count

    c = start(sessions, config, uid, now=later).analysis  # abandoned runs don't use up the allowance
    assert c.entitlement == "free"
    start(sessions, config, uid, now=later + timedelta(hours=config.analyses.usable_hours, minutes=1))
    assert sql(pg_engine, "SELECT failure_reason FROM analyses WHERE id = :a", a=c.id) == "abandoned"


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


def tailor_body(client):
    resume = client.post("/api/resume/parse", files={"file": ("r.txt", fixture_text("resume_analyst.txt"))}).json()
    jd = client.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")}).json()
    return {"resume": resume, "jd": jd}


def test_start_needs_sign_in(client):
    assert client.post("/api/analyses").status_code in (401, 403)


def test_402_no_credits_past_the_free_allowance_without_a_pass_or_credits(client, signed_in, pg_engine):
    for i in range(2):
        res = client.post("/api/analyses", headers={"Idempotency-Key": f"k{i}"})
        assert res.status_code == 200 and res.json()["pays_with"] == "free"
    res = client.post("/api/analyses", headers={"Idempotency-Key": "k3"})
    assert (res.status_code, res.json()["detail"]) == (402, "no_credits")
    assert sql(pg_engine, "SELECT count(*) FROM analyses WHERE user_id = :u", u=signed_in) == 2


def test_allowance_says_what_is_left_and_what_the_next_run_uses(client, signed_in, pg_engine):
    res = client.get("/api/analyses/allowance").json()
    assert (res["free_allowance"], res["free_used"], res["next_uses"], res["credits_balance"]) == (2, 0, "free", 0)
    assert res["resets_at"].endswith(("+00:00", "Z")) and res["resets_at"][8:10] == "01"
    client.post("/api/analyses", headers={"Idempotency-Key": "a"})
    client.post("/api/analyses", headers={"Idempotency-Key": "b"})
    assert client.get("/api/analyses/allowance").json()["next_uses"] is None
    asyncio.run(_txn_engine(pg_engine, lambda db: ledger.grant(db, signed_in, 1, reason="purchase",
                                                                idempotency_key="p1")))
    res = client.get("/api/analyses/allowance").json()
    assert (res["free_used"], res["next_uses"], res["credits_balance"]) == (2, "credit", 1)


def test_allowance_needs_sign_in(client):
    assert client.get("/api/analyses/allowance").status_code == 401


def test_claude_tailoring_counts_the_run_tags_usage_and_charges_nothing(client, signed_in, pg_engine, monkeypatch):
    asyncio.run(_txn_engine(pg_engine, lambda db: ledger.grant(db, signed_in, 1, reason="purchase",
                                                                idempotency_key="p1")))
    claude = FakeClaude()
    monkeypatch.setattr(routes, "get_llm", lambda: claude)
    started = client.post("/api/analyses").json()
    assert (started["pays_with"], started["remaining"]) == ("free", 1)
    aid = started["analysis_id"]

    res = client.post("/api/tailor", json=tailor_body(client), headers={"X-Analysis-Id": aid})
    assert res.status_code == 200
    assert claude.seen == [uuid.UUID(aid)]  # llm_usage rows get the server-side analysis id
    assert sql(pg_engine, "SELECT status FROM analyses WHERE id = :a", a=aid) == "succeeded"
    assert state(pg_engine, signed_in) == (1, 1)

    # Claude tailors once per analysis; a repeat is rules-only and changes nothing.
    again = client.post("/api/tailor", json=tailor_body(client), headers={"X-Analysis-Id": aid}).json()
    assert len(claude.seen) == 1 and any("start an analysis" in n for n in again["notes"])


def test_rules_only_fallback_doesnt_count(client, signed_in, pg_engine, monkeypatch):
    monkeypatch.setattr(routes, "get_llm", lambda: FakeClaude(fail=True))
    aid = client.post("/api/analyses").json()["analysis_id"]
    res = client.post("/api/tailor", json=tailor_body(client), headers={"X-Analysis-Id": aid}).json()
    assert any("doesn't count toward your tailorings" in n for n in res["notes"])
    assert sql(pg_engine, "SELECT status || '/' || failure_reason FROM analyses WHERE id = :a", a=aid) \
        == "failed/llm_degraded"
    assert client.get("/api/analyses/allowance").json()["free_used"] == 0


def test_a_crash_while_tailoring_releases_the_run(client, signed_in, pg_engine, monkeypatch):
    monkeypatch.setattr(routes, "get_llm", lambda: FakeClaude())

    def boom(*args):
        raise RuntimeError("bug")
    monkeypatch.setattr(routes, "tailor", boom)
    aid = client.post("/api/analyses").json()["analysis_id"]
    with pytest.raises(RuntimeError):
        client.post("/api/tailor", json=tailor_body(client), headers={"X-Analysis-Id": aid})
    assert sql(pg_engine, "SELECT failure_reason FROM analyses WHERE id = :a", a=aid) == "error"
    assert client.get("/api/analyses/allowance").json()["free_used"] == 0


def test_someone_elses_or_no_analysis_means_rules_only(client, new_browser, signed_in, pg_engine, monkeypatch):
    claude = FakeClaude()
    monkeypatch.setattr(routes, "get_llm", lambda: claude)
    aid = client.post("/api/analyses").json()["analysis_id"]
    body = tailor_body(client)

    stranger = new_browser()
    res = stranger.post("/api/gap/analyze", json=body, headers={"X-Analysis-Id": aid}).json()
    assert res["notes"] == ["Rules only (sign in and start an analysis to use Claude)."]
    res = client.post("/api/tailor", json=body, headers={"X-Analysis-Id": str(uuid.uuid4())})
    assert res.status_code == 200
    assert claude.seen == []
    assert sql(pg_engine, "SELECT status FROM analyses WHERE id = :a", a=aid) == "pending"
