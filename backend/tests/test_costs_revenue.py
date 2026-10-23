"""Step 7: every Claude call recorded (failures too), budgets with the kill switch and
alerts, the daily rollups, and the admin revenue / costs / refund endpoints. Includes the
spec's check that the kill switch pauses new analyses at the cap and resumes after reset."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import anthropic
import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.billing import payment_provider
from app.billing import aggregates, budget
from app.billing.config import load_billing_config
from app.billing.costs import current_analysis_id, pipeline_step, record_llm_usage
from app.billing.providers.base import RefundResult
from app.llm.client import ClaudeLLM, LLMError
from tests.conftest import TABLES, fixture_text
from tests.test_admin_security import audit_rows, make_user, signed_in
from tests.test_auth_signin import scalar
from tests.test_billing_admin import response
from tests.test_billing_webhooks import make_payment
from tests.test_llm_client import Out, StubClient, resp


@pytest.fixture(autouse=True)
def _clean(request):
    yield
    if "pg_engine" in request.fixturenames:
        with request.getfixturevalue("pg_engine").begin() as conn:
            conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))


def run(pg_engine, fn):
    """Run an async db function against the test database."""
    async def go():
        engine = create_async_engine(pg_engine.url.render_as_string(hide_password=False))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                return await fn(db)
        finally:
            await engine.dispose()
    return asyncio.run(go())


def usage(pg_engine, *, cost="1.0", status="ok", stage="_LLMTailored", model="claude-opus-5-5", analysis=None,
          user=None, at=None):
    with pg_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO llm_usage (analysis_id, user_id, stage, model, input_tokens, output_tokens, cost_usd, status,"
            " created_at) VALUES (:a, :u, :s, :m, 100, 50, :c, :st, :t)"),
            {"a": analysis, "u": user, "s": stage, "m": model, "c": cost, "st": status, "t": at or datetime.now(UTC)})


def analysis(pg_engine, uid, entitlement="free"):
    with pg_engine.begin() as conn:
        return conn.execute(text(
            "INSERT INTO analyses (user_id, idempotency_key, resume, jd, inputs_sha256, usable_until, entitlement)"
            " VALUES (:u, :k, '{}', '{}', 'x', now(), :e) RETURNING id"),
            {"u": uid, "k": uuid.uuid4().hex, "e": entitlement}).scalar_one()


# --- recording every call -----------------------------------------------------------------------


def _api_error(kind):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    if kind == "rate":
        return anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=request), body=None)
    return anthropic.APIConnectionError(request=request)


class Failing(StubClient):
    def __init__(self, exc):
        super().__init__(None)
        self.exc = exc

    def _parse(self, **kwargs):
        raise self.exc


@pytest.mark.parametrize("stub,status,code", [
    (StubClient(resp()), "ok", None), (StubClient(resp("refusal")), "refused", None),
    (StubClient(resp("max_tokens")), "truncated", None), (StubClient(resp(parsed=None)), "invalid", None),
    (Failing(_api_error("rate")), "rate_limited", "api_429"), (Failing(_api_error("conn")), "error", "connection"),
])
def test_the_client_reports_every_outcome(stub, status, code):
    seen = []
    llm = ClaudeLLM(client=stub, on_usage=lambda stage, r, **kw: seen.append((stage, r is not None, kw)))
    try:
        llm.parse(system="s", user="u", schema=Out)
    except LLMError:
        pass
    [(stage, answered, kw)] = seen
    assert stage == "Out" and kw["status"] == status and kw["error_code"] == code
    assert answered == (code is None) and isinstance(kw["latency_ms"], int) and kw["latency_ms"] >= 0


def test_recorded_rows_carry_user_status_and_latency(pg_url, pg_engine, monkeypatch):
    from app.billing import costs
    monkeypatch.setenv("RT_DATABASE_URL", pg_url)
    costs._engine.cache_clear()
    uid = make_user(pg_engine, "ada@example.com")
    aid = analysis(pg_engine, uid)
    token = current_analysis_id.set(aid)
    try:
        record_llm_usage("_LLMTailored", response(), latency_ms=1234, status="ok")
        record_llm_usage("_Items", None, latency_ms=50, status="rate_limited", error_code="api_429")
    finally:
        current_analysis_id.reset(token)
        costs._engine.cache_clear()
    with pg_engine.connect() as conn:
        rows = conn.execute(text("SELECT stage, user_id, status, latency_ms, error_code, cost_usd, input_tokens"
                                 " FROM llm_usage ORDER BY id")).all()
    assert [(r.stage, r.user_id, r.status, r.latency_ms, r.error_code) for r in rows] == [
        ("_LLMTailored", uid, "ok", 1234, None), ("_Items", uid, "rate_limited", 50, "api_429")]
    assert rows[0].cost_usd > 0 and rows[1].cost_usd == 0 and rows[1].input_tokens == 0


def test_pipeline_steps_have_names():
    assert [pipeline_step(s) for s in ("_Verdicts", "_LLMTailored", "_LLMRepaired", "_Lines", "_Items", "Other")] == [
        "gap_analysis", "tailor", "tailor_repair", "ats_semantic", "mentor", "Other"]


# --- the kill switch -----------------------------------------------------------------------------


def start(browser):
    resume = browser.post("/api/resume/parse", files={"file": ("r.txt", fixture_text("resume_analyst.txt"))}).json()
    jd = browser.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")}).json()
    return browser.post("/api/analyses", json={"resume": resume, "jd": jd})


def test_kill_switch_pauses_new_analyses_at_the_cap_and_resumes_after_reset(new_browser, pg_engine):
    boss, _ = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    user, uid = signed_in(new_browser, pg_engine, "user", "ada@example.com")
    assert boss.put("/api/admin/settings/daily_budget_usd", json={"value": 5, "reason": "tight budget"}).status_code == 200
    usage(pg_engine, cost="4.99")
    assert start(user).status_code == 200  # under the cap
    usage(pg_engine, cost="0.02")  # now 5.01 >= 5
    res = start(user)
    assert (res.status_code, res.json()["detail"]) == (503, "analyses_paused")
    # Tomorrow the day's spend starts again (the month has room).
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert run(pg_engine, lambda db: budget.pause_reason(db, tomorrow)) in (None, "monthly_budget")
    assert run(pg_engine, lambda db: budget.pause_reason(db)) == "daily_budget"
    # Raising the budget resumes it at once; so does turning the kill switch off.
    assert boss.put("/api/admin/settings/daily_budget_usd", json={"value": 50, "reason": "approved"}).status_code == 200
    assert start(user).status_code == 200


def test_monthly_cap_and_manual_pause(new_browser, pg_engine):
    boss, _ = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    user, _ = signed_in(new_browser, pg_engine, "user", "ada@example.com")
    boss.put("/api/admin/settings/monthly_budget_usd", json={"value": 10, "reason": "month cap"})
    usage(pg_engine, cost="10", at=datetime.now(UTC).replace(day=1, hour=0, minute=1))
    assert start(user).json()["detail"] == "analyses_paused"
    assert run(pg_engine, lambda db: budget.pause_reason(db)) == "monthly_budget"
    boss.put("/api/admin/settings/budget_kill_switch", json={"value": False, "reason": "launch day"})
    assert start(user).status_code == 200  # over budget, but the switch is off
    boss.put("/api/admin/settings/analyses_paused", json={"value": True, "reason": "incident"})
    assert start(user).json()["detail"] == "analyses_paused"
    assert run(pg_engine, lambda db: budget.pause_reason(db)) == "manual"


def test_yesterdays_spend_doesnt_count_today(new_browser, pg_engine):
    boss, _ = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    user, _ = signed_in(new_browser, pg_engine, "user", "ada@example.com")
    boss.put("/api/admin/settings/daily_budget_usd", json={"value": 5, "reason": "tight budget"})
    usage(pg_engine, cost="9", at=datetime.now(UTC) - timedelta(days=1, hours=1))
    if datetime.now(UTC).day == 1:  # yesterday was last month: nothing to compare
        return
    assert start(user).status_code == 200


def test_analyses_record_what_allowed_them(new_browser, pg_engine):
    user, uid = signed_in(new_browser, pg_engine, "user", "ada@example.com")
    aid = start(user).json()["analysis_id"]
    assert scalar(pg_engine, "SELECT entitlement FROM analyses WHERE id = :a", a=aid) == "free"


# --- alerts --------------------------------------------------------------------------------------


def test_budget_alerts_go_out_once_per_threshold(pg_engine, outbox, monkeypatch):
    make_user(pg_engine, "admin@example.com", "admin")
    make_user(pg_engine, "support@example.com", "support")  # not alerted
    posts = []

    def slack(request):
        posts.append((str(request.url), json.loads(request.content)))
        return httpx2.Response(200)

    monkeypatch.setenv("RT_SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/x")
    budget.set_slack_transport(httpx2.MockTransport(slack))
    try:
        with pg_engine.begin() as conn:
            conn.execute(text("INSERT INTO app_settings (key, value) VALUES ('daily_budget_usd', '10'),"
                              " ('monthly_budget_usd', '1000')"))
        usage(pg_engine, cost="8.5")
        sent = run(pg_engine, budget.check_and_alert)
        today = f"day:{datetime.now(UTC):%Y-%m-%d}"
        assert sent == [(today, 50), (today, 80)]
        assert {m.to for m in outbox} == {"admin@example.com"} and len(outbox) == 2
        assert "$8.50 of $10.00 (80% reached)" in outbox[-1].lines[0]
        assert [p[0] for p in posts] == ["https://hooks.slack.com/services/T/B/x"] * 2
        assert run(pg_engine, budget.check_and_alert) == []  # once each
        usage(pg_engine, cost="2")
        assert run(pg_engine, budget.check_and_alert) == [(today, 100)]
        assert "New analyses are paused" in outbox[-1].lines[0]
    finally:
        budget.set_slack_transport(None)


def test_slack_is_only_posted_to_slack(pg_engine, outbox, monkeypatch):
    monkeypatch.setenv("RT_SLACK_WEBHOOK_URL", "https://evil.example/hook")
    calls = []
    budget.set_slack_transport(httpx2.MockTransport(lambda r: calls.append(r) or httpx2.Response(200)))
    try:
        with pg_engine.begin() as conn:
            conn.execute(text("INSERT INTO app_settings (key, value) VALUES ('daily_budget_usd', '1')"))
        usage(pg_engine, cost="1")
        assert run(pg_engine, budget.check_and_alert)
        assert calls == []
    finally:
        budget.set_slack_transport(None)


# --- rollups -------------------------------------------------------------------------------------


def paid_payment(pg_engine, uid, *, amount=600, settled=560, tax=0, refunded=0, status="paid", when=None):
    pid = make_payment(pg_engine, uid, checkout_id=uuid.uuid4().hex)
    with pg_engine.begin() as conn:
        conn.execute(text(
            "UPDATE payments SET status = :s, amount_minor = :a, currency = 'USD', settlement_amount_minor = :st,"
            " settlement_currency = 'USD', settlement_tax_minor = :t, refunded_amount_minor = :r, paid_at = :w,"
            " provider_payment_id = :pp WHERE id = :id"),
            {"s": status, "a": amount, "st": settled, "t": tax, "r": refunded, "w": when or datetime.now(UTC),
             "pp": f"pay_{uuid.uuid4().hex[:8]}", "id": pid})
    return pid


def test_refresh_rolls_up_costs_and_revenue_idempotently(pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    free, paid = analysis(pg_engine, uid, "free"), analysis(pg_engine, uid, "credit")
    usage(pg_engine, cost="0.5", analysis=free, stage="_LLMTailored")
    usage(pg_engine, cost="0.25", analysis=free, stage="_LLMTailored", status="refused")
    usage(pg_engine, cost="1", analysis=paid, stage="_Items")
    usage(pg_engine, cost="7", at=datetime.now(UTC) - timedelta(days=10))  # outside a 3-day refresh
    paid_payment(pg_engine, uid)
    config = load_billing_config()
    first = run(pg_engine, lambda db: aggregates.refresh(db, config, days=3))
    again = run(pg_engine, lambda db: aggregates.refresh(db, config, days=3))
    assert first == again
    with pg_engine.connect() as conn:
        rows = {(r.stage, r.entitlement): r for r in conn.execute(text("SELECT * FROM daily_llm_costs")).all()}
        rev = conn.execute(text("SELECT * FROM daily_revenue")).one()
    tailor = rows[("tailor", "free")]
    assert (tailor.calls, tailor.failed, float(tailor.cost_usd), float(tailor.wasted_usd)) == (2, 1, 0.75, 0.25)
    assert float(rows[("mentor", "credit")].cost_usd) == 1.0
    assert ("tailor", "none") not in rows  # the 10-day-old row wasn't in the window
    assert (rev.payments, rev.gross_minor, rev.settled_usd_cents) == (1, 600, 560) and rev.fees_usd_cents > 0
    run(pg_engine, lambda db: aggregates.refresh(db, config, days=30))
    assert scalar(pg_engine, "SELECT count(*) FROM daily_llm_costs") == 3


# --- admin endpoints -----------------------------------------------------------------------------


def test_revenue_view(new_browser, pg_engine):
    admin, _ = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    support, _ = signed_in(new_browser, pg_engine, "support", "support@example.com")
    uid = make_user(pg_engine, "ada@example.com")
    paid_payment(pg_engine, uid)
    paid_payment(pg_engine, uid, refunded=600, status="refunded")
    with pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO credit_transactions (user_id, delta, reason, idempotency_key, balance_after)"
                          " VALUES (:u, 2, 'referral', 'r1', 2)"), {"u": uid})
    run(pg_engine, lambda db: aggregates.refresh(db, load_billing_config(), days=3))
    assert support.get("/api/admin/revenue").status_code == 403
    out = admin.get("/api/admin/revenue").json()
    assert len(out["daily"]) == 30 and out["daily"][0]["gross_usd"] == 0  # every day, quiet ones as zero
    t = out["totals"]
    assert (t["payments"], t["gross_usd"], t["refunds_usd"]) == (2, 11.2, 5.6)
    assert t["net_after_fees_usd"] == round(t["net_usd"] - t["fees_usd"], 2) and out["as_of"]
    assert out["by_product"][0]["product_key"] == "credit_pack_5"
    assert out["referral_liability"]["credits_granted_in_window"] == 2
    assert out["referral_liability"]["est_value_usd"] == round(2 * 6.00 / 5, 2)  # $6 pack of 5 credits


class FakeProvider:
    mode = "test"

    def __init__(self):
        self.calls = []

    async def refund(self, payment_id, *, reason, amount_minor=None, item_id=None, metadata=None):
        self.calls.append((payment_id, amount_minor, item_id))
        return RefundResult(provider_refund_id="rfd_9", status="pending")


def test_refunds_go_through_the_provider_and_are_audited(api_app, new_browser, pg_engine):
    fake = FakeProvider()
    api_app.dependency_overrides[payment_provider] = lambda: fake
    admin, admin_id = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    support, _ = signed_in(new_browser, pg_engine, "support", "support@example.com")
    uid = make_user(pg_engine, "ada@example.com")
    pid = paid_payment(pg_engine, uid)
    listed = admin.get("/api/admin/revenue/payments").json()
    assert listed["total"] == 1 and listed["items"][0]["user_email"] == "ada@example.com"
    assert support.post(f"/api/admin/revenue/payments/{pid}/refund", json={"reason": "duplicate"}).status_code == 403
    assert admin.post(f"/api/admin/revenue/payments/{pid}/refund", json={"amount_minor": 601, "reason": "too much"}).json()[
        "detail"] == "more_than_paid"
    res = admin.post(f"/api/admin/revenue/payments/{pid}/refund", json={"reason": "charged twice"})
    assert res.json() == {"provider_refund_id": "rfd_9", "status": "pending"}
    provider_id = scalar(pg_engine, "SELECT provider_payment_id FROM payments WHERE id = :p", p=pid)
    assert fake.calls == [(provider_id, None, None)]
    [row] = audit_rows(pg_engine, pid)
    assert (row["action"], row["actor_id"], row["after"]["requested_minor"]) == ("billing.refund", admin_id, 600)
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE payments SET status = 'refunded' WHERE id = :p"), {"p": pid})
    assert admin.post(f"/api/admin/revenue/payments/{pid}/refund", json={"reason": "again"}).json()["detail"] == "not_refundable"


def test_a_partial_refund_needs_the_products_dodo_id(api_app, new_browser, pg_engine):
    fake = FakeProvider()
    api_app.dependency_overrides[payment_provider] = lambda: fake
    admin, _ = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    pid = paid_payment(pg_engine, make_user(pg_engine, "ada@example.com"))
    res = admin.post(f"/api/admin/revenue/payments/{pid}/refund", json={"amount_minor": 100, "reason": "partial"})
    assert (res.status_code, res.json()["detail"]) == (409, "partial_needs_product_id")  # billing.toml ids are blank
    assert fake.calls == []


def test_costs_view(new_browser, pg_engine):
    admin, _ = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    support, _ = signed_in(new_browser, pg_engine, "support", "support@example.com")
    uid = make_user(pg_engine, "ada@example.com")
    a1, a2 = analysis(pg_engine, uid, "free"), analysis(pg_engine, uid, "credit")
    usage(pg_engine, cost="1", analysis=a1, user=uid, stage="_LLMTailored")
    usage(pg_engine, cost="0.5", analysis=a1, user=uid, stage="_Items", status="truncated")
    usage(pg_engine, cost="3", analysis=a2, user=uid, stage="_LLMTailored", model="claude-sonnet-5-5")
    paid_payment(pg_engine, uid)
    run(pg_engine, lambda db: aggregates.refresh(db, load_billing_config(), days=3))
    assert support.get("/api/admin/costs").status_code == 403
    out = admin.get("/api/admin/costs", params={"granularity": "month"}).json()
    assert out["total_usd"] == 4.5 and out["calls"] == 3 and out["failed_calls"] == 1 and out["wasted_usd"] == 0.5
    assert out["free_tier_usd"] == 1.5 and sum(x["cost_usd"] for x in out["series"]) == 4.5
    assert len(out["series"]) in (1, 2) and out["series"][-1]["period"] == f"{datetime.now(UTC):%Y-%m}"  # every month in the window
    daily = admin.get("/api/admin/costs", params={"days": 7}).json()["series"]
    assert len(daily) == 7 and sum(x["calls"] for x in daily) == 3  # quiet days are zero, not missing
    assert {s["key"]: s["cost_usd"] for s in out["by_step"]} == {"tailor": 4.0, "mentor": 0.5}
    assert {m["key"] for m in out["by_model"]} == {"claude-opus-5-5", "claude-sonnet-5-5"}
    assert out["per_analysis"] == {"analyses": 2, "avg_usd": 2.25, "p95_usd": pytest.approx(2.925, abs=1e-3)}
    assert out["top_users"][0]["email"] == "ada@example.com" and out["top_users"][0]["cost_usd"] == 4.5
    assert out["margin"]["analyses"] == 2 and out["margin"]["cost_per_analysis_usd"] == 2.25
    assert out["budget"]["today_usd"] == 4.5 and out["budget"]["kill_switch"] is True
    assert any(p["model"] == "claude-opus-5-5" for p in out["prices"])
