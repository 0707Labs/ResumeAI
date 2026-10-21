"""Tailoring is free to try, the clean download pays: the entitlement decisions (pure and
against Postgres), the start gate past the free tailorings, download charging with the
re-download window, no overspend or double charge under concurrency, a failed export
charging nothing, the 402 paths, signed short-lived download links, files built from the
pinned inputs, and the pipeline using Claude only for the caller's own analysis."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import routes
from app.auth.signing import sign
from app.billing import analyses, ledger
from app.billing.analyses import NoEntitlement, UnknownAnalysis
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


def test_download_order_is_pass_then_pro_then_credit_and_never_free():
    everything = dict(credits=5, passes=[CapUsage(P1, 0, 40)], pro=CapUsage(SUB, 0, 100))
    assert can_user_run(snap(**everything)).pays_with == "pass"
    assert can_user_run(snap(**{**everything, "passes": []})).pays_with == "pro"
    d = can_user_run(snap(credits=5))
    assert (d.pays_with, d.remaining) == ("credit", 4)
    d = can_user_run(snap(free_allowance=5))  # free tailorings don't make downloads free
    assert (d.allowed, d.reason) == (False, "no_credits")


def test_caps_fall_through_to_credits():
    d = can_user_run(snap(credits=2, passes=[CapUsage(P1, 40, 40), CapUsage(P2, 3, 40)]))
    assert (d.pays_with, d.pass_id, d.remaining) == ("pass", P2, 36)
    d = can_user_run(snap(credits=2, passes=[CapUsage(P1, 40, 40)], pro=CapUsage(SUB, 100, 100)))
    assert (d.pays_with, d.remaining) == ("credit", 1)


def test_tailoring_uses_the_free_allowance_then_needs_what_a_download_needs():
    assert can_start_tailoring(snap(credits=5)).pays_with == "free"
    assert can_start_tailoring(snap(free_used=1)).remaining == 0
    d = can_start_tailoring(snap(free_used=2, credits=3))
    assert (d.pays_with, d.remaining) == ("credit", 3)  # nothing is spent at start
    d = can_start_tailoring(snap(free_used=2, passes=[CapUsage(P1, 5, 40)]))
    assert (d.pays_with, d.remaining) == ("pass", 35)
    d = can_start_tailoring(snap(free_used=2))
    assert (d.allowed, d.reason, d.pays_with) == (False, "no_credits", None)


# --- against Postgres ---------------------------------------------------------------------------


@pytest.fixture
def sessions(pg_url, pg_engine):
    engine = create_async_engine(pg_url, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE downloads, analyses, credit_transactions, passes, subscriptions, users CASCADE"))


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


def pay(sessions, config, uid, aid, now=NOW, fmt="docx"):
    return run(sessions, lambda db: analyses.pay_for_download(db, config, uid, aid, fmt=fmt,
                                                              final_resume={"name": "Ada"}, now=now))


def rules_only(pg_engine, aid):
    """Mark a run as tailored without Claude (it stops counting as a free tailoring)."""
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE analyses SET tailored = '{}', llm_tailored = false, tailored_at = now()"
                          " WHERE id = :a"), {"a": aid})


def no_free(config, n=0):
    return config.model_copy(update={"free": config.free.model_copy(update={"analyses_per_month": n})})


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


def test_starting_spends_nothing_and_is_idempotent(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=3)
    key = lambda db: analyses.start_analysis(db, config, uid, resume={"name": "Ada"}, jd={"raw_text": "A job"},  # noqa: E731
                                             idempotency_key="click-1", now=NOW)
    first, again = run(sessions, key), run(sessions, key)
    assert again.replay and again.analysis.id == first.analysis.id
    for _ in range(4):  # 1 more free, then backed by the balance
        start(sessions, config, uid)
    assert state(pg_engine, uid) == (3, 3)
    assert sql(pg_engine, "SELECT count(*) FROM analyses WHERE user_id = :u", u=uid) == 5


def test_past_the_free_tailorings_starting_needs_a_pass_pro_or_credits(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    start(sessions, config, uid, now=NOW - timedelta(days=25))  # last month's doesn't count
    start(sessions, config, uid)
    rules_only(pg_engine, start(sessions, config, uid))  # ended rules-only: doesn't count
    start(sessions, config, uid)
    with pytest.raises(NoEntitlement) as denied:
        start(sessions, config, uid)
    assert denied.value.decision.reason == "no_credits"
    give_credits(pg_engine, uid, 1)
    start(sessions, config, uid)
    add_pass(pg_engine, uid)
    start(sessions, config, uid)
    assert state(pg_engine, uid) == (1, 1)


def test_the_free_allowance_is_configurable(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    for _ in range(5):
        start(sessions, no_free(config, 5), uid)
    with pytest.raises(NoEntitlement):
        start(sessions, no_free(config, 5), uid)


def test_a_download_charges_one_credit_and_re_downloads_in_the_window_are_free(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=2)
    aid = start(sessions, config, uid)
    first = pay(sessions, config, uid, aid)
    assert (first.download.paid_with, first.download.credits) == ("credit", 1)
    assert state(pg_engine, uid) == (1, 1)
    assert sql(pg_engine, "SELECT idempotency_key FROM credit_transactions WHERE reason = 'analysis_charge'") \
        == f"download:{first.download.id}"
    for when, fmt in [(NOW + timedelta(hours=1), "pdf"), (NOW + timedelta(days=6, hours=23), "docx")]:
        again = pay(sessions, config, uid, aid, now=when, fmt=fmt)
        assert again.download.paid_with == "window" and again.decision is None
    assert state(pg_engine, uid) == (1, 1)

    later = pay(sessions, config, uid, aid, now=NOW + timedelta(days=7, minutes=1))  # the window has passed
    assert later.download.paid_with == "credit"
    assert state(pg_engine, uid) == (0, 0)
    assert sql(pg_engine, "SELECT count(*) FROM downloads WHERE analysis_id = :a", a=aid) == 4


def test_the_redownload_window_is_configurable(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=2)
    aid = start(sessions, config, uid)
    none = config.model_copy(update={"downloads": config.downloads.model_copy(update={"redownload_free_days": 0})})
    pay(sessions, none, uid, aid)
    pay(sessions, none, uid, aid, now=NOW + timedelta(seconds=1))
    assert state(pg_engine, uid) == (0, 0)


def test_a_new_tailoring_is_a_new_download(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=2)
    a, b = start(sessions, config, uid), start(sessions, config, uid)
    pay(sessions, config, uid, a)
    assert pay(sessions, config, uid, b).download.paid_with == "credit"
    assert state(pg_engine, uid) == (0, 0)


def test_download_order_against_the_database(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=1)
    add_pass(pg_engine, uid, revoked=True)
    add_pass(pg_engine, uid, starts=NOW - timedelta(days=40))  # expired
    add_pass(pg_engine, uid, starts=NOW + timedelta(days=1))  # queued, not started
    add_pro(pg_engine, uid, status="on_hold")
    add_pro(pg_engine, uid, period_end=NOW - timedelta(days=1))
    nobody = new_user(pg_engine)
    with pytest.raises(NoEntitlement):  # free tailorings don't cover downloads
        pay(sessions, config, nobody, start(sessions, config, nobody))

    live = add_pass(pg_engine, uid, cap=1)
    d = pay(sessions, config, uid, start(sessions, config, uid)).download
    assert (d.paid_with, d.pass_id) == ("pass", live)
    pro = add_pro(pg_engine, uid)
    d = pay(sessions, config, uid, start(sessions, config, uid)).download  # the pass is at its cap of 1
    assert (d.paid_with, d.subscription_id) == ("pro", pro)
    assert state(pg_engine, uid) == (1, 1)


def test_someone_elses_analysis_cant_be_paid_for(sessions, config, pg_engine):
    owner, other = new_user(pg_engine), new_user(pg_engine, credits=1)
    aid = start(sessions, config, owner)
    with pytest.raises(UnknownAnalysis):
        pay(sessions, config, other, aid)
    assert state(pg_engine, other) == (1, 1)


def test_concurrent_clicks_on_one_download_charge_once(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=3)
    aid = start(sessions, config, uid)
    results = concurrently(sessions, 8, lambda db, i: analyses.pay_for_download(
        db, config, uid, aid, fmt="docx", final_resume={}, now=NOW))
    assert all(isinstance(r, analyses.Paid) for r in results), results
    assert sorted(r.download.paid_with for r in results) == ["credit"] + ["window"] * 7
    assert state(pg_engine, uid) == (2, 2)


def test_concurrent_downloads_never_overspend_or_go_negative(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=2)
    ids = [start(sessions, config, uid) for _ in range(6)]
    results = concurrently(sessions, 6, lambda db, i: analyses.pay_for_download(
        db, config, uid, ids[i], fmt="pdf", final_resume={}, now=NOW))
    assert sum(isinstance(r, analyses.Paid) for r in results) == 2
    assert all(isinstance(r, analyses.Paid | NoEntitlement) for r in results)
    assert state(pg_engine, uid) == (0, 0)


def test_concurrent_downloads_never_exceed_a_pass_cap(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    pass_id = add_pass(pg_engine, uid, cap=3)
    ids = [start(sessions, no_free(config, 8), uid) for _ in range(8)]
    results = concurrently(sessions, 8, lambda db, i: analyses.pay_for_download(
        db, config, uid, ids[i], fmt="docx", final_resume={}, now=NOW))
    paid = [r.download for r in results if isinstance(r, analyses.Paid)]
    assert len(paid) == 3 and all(d.pass_id == pass_id for d in paid)


def test_concurrent_starts_never_exceed_the_free_tailorings(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    results = concurrently(sessions, 8, lambda db, i: analyses.start_analysis(
        db, config, uid, resume={"name": "Ada"}, jd={"raw_text": "A job"}, idempotency_key=str(i), now=NOW))
    assert sum(isinstance(r, analyses.Started) for r in results) == 2


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
    """Ask for a download (the paid step); returns the response with the signed link."""
    headers = {"X-Analysis-Id": aid} if aid else {}
    return client.post(f"/api/downloads/{fmt}", headers=headers, json={
        "resume": inputs["resume"], "tailored": tailoring, "jd_text": inputs["jd"]["raw_text"], **body})


def fetch(client, link_res):
    assert link_res.status_code == 200, link_res.text
    return client.get(link_res.json()["url"])


def test_start_needs_sign_in(client, inputs):
    assert client.post("/api/analyses", json=inputs).status_code == 401


def test_start_says_what_allowed_it_and_402s_past_the_free_tailorings(client, signed_in, inputs, pg_engine):
    for _ in range(2):
        res = client.post("/api/analyses", json=inputs)
        assert res.status_code == 200 and res.json()["uses"] == "free"
    res = client.post("/api/analyses", json=inputs)
    assert (res.status_code, res.json()["detail"]) == (402, "no_credits")
    give_credits(pg_engine, signed_in, 1)
    assert client.post("/api/analyses", json=inputs).json()["uses"] == "credit"
    assert state(pg_engine, signed_in) == (1, 1)


def test_allowance_says_what_is_left_and_what_the_next_run_uses(client, signed_in, inputs, pg_engine):
    res = client.get("/api/analyses/allowance").json()
    assert (res["free_allowance"], res["free_used"], res["next_uses"], res["credits_balance"]) == (2, 0, "free", 0)
    assert res["resets_at"][8:10] == "01"
    begin(client, inputs), begin(client, inputs)
    assert client.get("/api/analyses/allowance").json()["next_uses"] is None
    give_credits(pg_engine, signed_in, 1)
    res = client.get("/api/analyses/allowance").json()
    assert (res["free_used"], res["next_uses"], res["credits_balance"]) == (2, "credit", 1)


def test_allowance_needs_sign_in(client):
    assert client.get("/api/analyses/allowance").status_code == 401


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
    assert download(signed_out, inputs, None, tailoring).status_code in (401, 403)
    assert (res := download(client, inputs, None, tailoring)).status_code == 409
    assert res.json()["detail"] == "analysis_required"
    assert download(client, inputs, str(uuid.uuid4()), tailoring).status_code == 404


def test_without_entitlement_402_and_no_file_is_generated(client, signed_in, inputs, pg_engine, monkeypatch):
    rendered = []
    render = routes._render
    monkeypatch.setattr(routes, "_render", lambda *a: rendered.append(a) or render(*a))
    aid = begin(client, inputs)
    res = download(client, inputs, aid, tailored(client, inputs, aid))
    assert (res.status_code, res.json()["detail"]) == (402, "no_credits")
    assert rendered == []
    assert sql(pg_engine, "SELECT count(*) FROM downloads") == 0


def test_a_paid_download_gives_a_signed_link_and_re_downloads_are_free(client, signed_in, inputs, pg_engine):
    give_credits(pg_engine, signed_in, 1)
    aid = begin(client, inputs)
    tailoring = tailored(client, inputs, aid)
    link = download(client, inputs, aid, tailoring)
    body = link.json()
    assert (body["paid_with"], body["credits_balance"]) == ("credit", 0)
    assert body["url"].startswith("/api/downloads/file/")
    file = fetch(client, link)
    assert file.status_code == 200 and file.content[:2] == b"PK"
    assert file.headers["content-disposition"].startswith("attachment;")
    assert file.headers["cache-control"] == "no-store"

    pdf = download(client, inputs, aid, tailoring, fmt="pdf")  # same resume, within the window
    assert pdf.json()["paid_with"] == "window" and fetch(client, pdf).content[:4] == b"%PDF"
    assert state(pg_engine, signed_in) == (0, 0)
    assert sql(pg_engine, "SELECT count(*) FROM downloads WHERE served_at IS NOT NULL") == 2


def test_a_signed_link_is_for_its_owner_only_and_expires(client, new_browser, signed_in, inputs, pg_engine):
    give_credits(pg_engine, signed_in, 1)
    aid = begin(client, inputs)
    link = download(client, inputs, aid, tailored(client, inputs, aid)).json()
    assert client.__class__(client.app).get(link["url"]).status_code == 401  # signed out

    other = new_browser()
    assert other.post(f"/test/login/{new_user(pg_engine)}").status_code == 200
    assert other.get(link["url"]).status_code == 404  # someone else

    download_id = link["url"].rsplit("/", 1)[1].split(":")[0]
    expired = sign("download", f"{download_id}:{int(datetime.now(UTC).timestamp()) - 1}")
    assert (res := client.get(f"/api/downloads/file/{expired}")).status_code == 410
    assert res.json()["detail"] == "link_expired"
    forged = f"{download_id}:{int(datetime.now(UTC).timestamp()) + 999}.deadbeef"
    assert client.get(f"/api/downloads/file/{forged}").status_code == 404


def test_the_file_is_built_from_the_pinned_resume(client, signed_in, inputs, pg_engine):
    give_credits(pg_engine, signed_in, 1)
    aid = begin(client, inputs)
    tailoring = tailored(client, inputs, aid)
    swapped = {**inputs, "resume": {**inputs["resume"], "name": "Someone Else"}}
    file = fetch(client, download(client, swapped, aid, tailoring))
    assert "Someone_Else" not in file.headers["content-disposition"]


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
    assert sql(pg_engine, "SELECT count(*) FROM downloads") == 0

    monkeypatch.setattr(routes, "_render", render)
    assert fetch(client, download(client, inputs, aid, tailoring)).status_code == 200
    assert state(pg_engine, signed_in) == (0, 0)
    assert sql(pg_engine, "SELECT count(*) FROM credit_transactions WHERE reason = 'analysis_charge'") == 1


def test_download_events_are_logged_without_resume_text(client, signed_in, inputs, pg_engine, caplog):
    give_credits(pg_engine, signed_in, 1)
    aid = begin(client, inputs)
    with caplog.at_level(logging.INFO, logger="app.billing"):
        download(client, inputs, aid, tailored(client, inputs, aid))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("download ")]
    assert len(lines) == 1 and f"analysis={aid}" in lines[0] and "paid_with=credit" in lines[0]
    name = inputs["resume"]["name"]
    assert all(name not in r.getMessage() for r in caplog.records)
