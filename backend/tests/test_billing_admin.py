"""Cost tracking and the admin billing view: pricing math, usage recording, analysis
grouping, admin-only access, margin after estimated Dodo fees, and alerts."""

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.billing import billing_config
from app.billing import costs
from app.billing.config import load_billing_config
from app.billing.costs import cost_usd, current_analysis_id, record_llm_usage, usage_row
from app.llm.client import ClaudeLLM
from app.main import create_app
from tests.test_auth_signin import count, csrf, scalar
from tests.test_billing_webhooks import PACK, make_payment
from tests.test_llm_client import Out, StubClient

CONFIG = load_billing_config()


def response(model="claude-opus-5-5", inp=1000, out=500, cache_read=0, cache_write=0):
    return SimpleNamespace(model=model, stop_reason="end_turn", parsed_output=Out(answer="ok"),
                           usage=SimpleNamespace(input_tokens=inp, output_tokens=out,
                                                 cache_read_input_tokens=cache_read,
                                                 cache_creation_input_tokens=cache_write))


# --- pricing and recording ---------------------------------------------------------------------


def test_cost_uses_configured_prices_per_million_tokens():
    assert cost_usd(CONFIG, "claude-opus-5-5", input_tokens=1_000_000, output_tokens=0) == Decimal("4")
    assert cost_usd(CONFIG, "claude-opus-5-5", input_tokens=1000, output_tokens=500,
                    cache_read_tokens=10_000, cache_write_tokens=2000) == Decimal("0.026")  # .004+.01+.002+.01
    assert cost_usd(CONFIG, "claude-mystery-9", input_tokens=1, output_tokens=1) is None


def test_usage_row_takes_the_answering_model_and_cache_tokens():
    token = current_analysis_id.set(uuid.UUID(int=1))
    try:
        row = usage_row("TailoredOut", response(model="claude-sonnet-5-5", cache_read=7), CONFIG)
    finally:
        current_analysis_id.reset(token)
    assert (row["model"], row["cache_read_tokens"], row["analysis_id"], row["stage"]) == \
        ("claude-sonnet-5-5", 7, uuid.UUID(int=1), "TailoredOut")


def test_llm_client_reports_every_response_including_refusals():
    seen = []
    refusal = response()
    refusal.stop_reason = "refusal"
    llm = ClaudeLLM(client=StubClient(refusal), on_usage=lambda stage, r: seen.append(stage))
    with pytest.raises(Exception):
        llm.parse(system="s", user="u", schema=Out)
    assert seen == ["Out"]


def test_record_llm_usage_writes_a_row(pg_url, pg_engine, monkeypatch):
    engine = create_engine(pg_url)
    monkeypatch.setattr(costs, "_engine", lambda: engine)
    try:
        record_llm_usage("GapOut", response())
    finally:
        engine.dispose()
    row = scalar(pg_engine, "SELECT row_to_json(u) FROM llm_usage u")
    assert (row["model"], row["input_tokens"], float(row["cost_usd"])) == ("claude-opus-5-5", 1000, 0.014)
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE llm_usage"))


def test_record_llm_usage_never_raises_without_a_database(monkeypatch):
    def broken():
        raise RuntimeError("no db")
    monkeypatch.setattr(costs, "_engine", broken)
    record_llm_usage("GapOut", response())  # no exception


def test_analysis_id_header_reaches_sync_pipeline_code():
    app = create_app()

    @app.get("/test/analysis-id")
    def read() -> dict:  # sync, like the pipeline routes
        value = current_analysis_id.get()
        return {"id": str(value) if value else None}

    with TestClient(app) as c:
        aid = str(uuid.uuid4())
        assert c.get("/test/analysis-id", headers={"X-Analysis-Id": aid}).json() == {"id": aid}
        assert c.get("/test/analysis-id", headers={"X-Analysis-Id": "nope"}).json() == {"id": None}
        assert c.get("/test/analysis-id").json() == {"id": None}


# --- admin view ----------------------------------------------------------------------------------


@pytest.fixture
def admin(client, user_id, pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET role = 'admin' WHERE id = :u"), {"u": user_id})
    assert client.post(f"/test/login/{user_id}").status_code == 200
    return user_id


@pytest.fixture
def clean_usage(pg_engine):
    yield
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE llm_usage"))


def sql(pg_engine, stmt, **params):
    with pg_engine.begin() as conn:
        conn.execute(text(stmt), params)


def add_usage(pg_engine, analysis_id, cost, model="claude-opus-5-5", when="now()"):
    sql(pg_engine, "INSERT INTO llm_usage (analysis_id, stage, model, input_tokens, output_tokens, cost_usd,"
                   f" created_at) VALUES (:a, 'GapOut', :m, 1, 1, :c, {when})", a=analysis_id, m=model, c=cost)


def test_admin_view_is_admin_only(client, user_id, new_browser):
    assert new_browser().get("/api/admin/billing/overview").status_code == 401
    client.post(f"/test/login/{user_id}")
    assert client.get("/api/admin/billing/overview").status_code == 403


def test_overview_reports_llm_cost_per_analysis(client, admin, pg_engine, clean_usage):
    a, b = uuid.uuid4(), uuid.uuid4()
    add_usage(pg_engine, a, 0.10)
    add_usage(pg_engine, a, 0.20)
    add_usage(pg_engine, b, 0.10)
    add_usage(pg_engine, None, None, model="claude-mystery-9")
    llm = client.get("/api/admin/billing/overview").json()["llm"]
    assert (llm["calls"], llm["analyses"], llm["unpriced_calls"]) == (4, 2, 1)
    assert llm["avg_cost_per_analysis_usd"] == pytest.approx(0.20)
    assert llm["total_cost_usd"] == pytest.approx(0.40)


def test_overview_margin_after_estimated_fees(client, admin, pg_engine, clean_usage):
    pid = make_payment(pg_engine, admin)
    sql(pg_engine, "UPDATE payments SET status = 'paid', paid_at = now(), currency = 'INR', amount_minor = 49900,"
                   " settlement_amount_minor = 600, settlement_currency = 'USD', settlement_tax_minor = 92"
                   " WHERE id = :i", i=pid)
    add_usage(pg_engine, uuid.uuid4(), 0.05)
    body = client.get("/api/admin/billing/overview").json()
    plan = body["margin"][0]
    fee = round(600 * 4.0 / 100 + 15)  # India: 4% + 15c on the settled amount
    assert (plan["product_key"], plan["units"], plan["settled_usd_cents"], plan["fees_usd_cents"]) == \
        ("credit_pack_5", 1, 508, fee)
    assert plan["net_usd_cents"] == 508 - fee
    assert plan["llm_cost_if_fully_used_usd_cents"] == 25  # 5 runs x $0.05
    assert plan["margin_if_fully_used_usd_cents"] == 508 - fee - 25
    assert body["fees_are_estimates"] is True


def test_overview_counts_credits_sold_and_consumed(client, admin, pg_engine):
    for i, (delta, reason) in enumerate([(5, "purchase"), (-1, "analysis_charge"), (-1, "analysis_charge"),
                                         (1, "refund"), (-2, "purchase_reversal")]):
        sql(pg_engine, "INSERT INTO credit_transactions (user_id, delta, reason, idempotency_key, balance_after)"
                       " VALUES (:u, :d, :r, :k, 1)", u=admin, d=delta, r=reason, k=f"k{i}")
    assert client.get("/api/admin/billing/overview").json()["credits"] == \
        {"sold": 5, "consumed": 1, "reversed": 2, "outstanding": 0}


def test_alerts_for_failing_webhooks_and_llm_spend(client, admin, pg_engine, clean_usage, api_app):
    config = CONFIG.model_copy(update={"alerts": CONFIG.alerts.model_copy(update={"daily_llm_spend_usd": 1.0})})
    api_app.dependency_overrides[billing_config] = lambda: config
    sql(pg_engine, "INSERT INTO processed_webhook_events (provider, event_id, event_type, occurred_at, failures,"
                   " last_error) VALUES ('dodo', 'msg_x', 'payment.succeeded', now(), 3, 'RuntimeError')")
    add_usage(pg_engine, uuid.uuid4(), 0.60)
    add_usage(pg_engine, uuid.uuid4(), 0.60)
    add_usage(pg_engine, uuid.uuid4(), 5.00, when="now() - interval '2 days'")  # not today
    body = client.get("/api/admin/billing/overview").json()
    kinds = {a["kind"]: a for a in body["alerts"]}
    assert set(kinds) == {"webhook_failing", "llm_spend"}
    assert "$1.20" in kinds["llm_spend"]["message"]
    assert body["failing_webhooks"][0]["event_id"] == "msg_x"


def test_no_alerts_when_all_is_well(client, admin, clean_usage):
    assert client.get("/api/admin/billing/overview").json()["alerts"] == []


def test_resolve_review(client, admin, pg_engine):
    pid = make_payment(pg_engine, admin)
    sql(pg_engine, "INSERT INTO billing_reviews (kind, dedupe_key, payment_id, detail) VALUES"
                   " ('credits_already_used', 'used:x', :p, CAST(:d AS jsonb))", p=pid,
        d=json.dumps({"shortfall": 3}))
    review = client.get("/api/admin/billing/overview").json()["reviews"][0]
    assert review["detail"] == {"shortfall": 3}
    assert client.post(f"/api/admin/billing/reviews/{review['id']}/resolve").status_code == 403  # no CSRF
    assert client.post(f"/api/admin/billing/reviews/{review['id']}/resolve", headers=csrf(client)).status_code == 204
    assert client.get("/api/admin/billing/overview").json()["reviews"] == []
    assert count(pg_engine, "billing_reviews", "resolved_at IS NOT NULL") == 1


def test_snapshot_fixture_has_credits():
    assert PACK["credits"] == 5


# --- admin CLI -------------------------------------------------------------------------------------


@pytest.fixture
def cli_db(pg_url, monkeypatch):
    from app.db import session
    monkeypatch.setenv("RT_DATABASE_URL", pg_url)
    session.get_engine.cache_clear()
    session.get_sessionmaker.cache_clear()
    yield
    session.get_engine.cache_clear()
    session.get_sessionmaker.cache_clear()


def test_adjust_credits_cli(cli_db, api_app, user_id, pg_engine, capsys):  # api_app: truncates after
    from app.billing.cli import main
    assert main(["adjust-credits", str(user_id), "3", "--note", "goodwill: ticket 12", "--key", "t12"]) == 0
    assert main(["adjust-credits", str(user_id), "3", "--note", "goodwill: ticket 12", "--key", "t12"]) == 0
    assert "Already applied" in capsys.readouterr().out
    assert main(["adjust-credits", str(user_id), "-5", "--note", "too many"]) == 1  # never below zero
    assert scalar(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=user_id) == 3
    assert scalar(pg_engine, "SELECT note FROM credit_transactions WHERE reason = 'admin_adjust'") == "goodwill: ticket 12"
    with pytest.raises(SystemExit):
        main(["adjust-credits", str(user_id), "1"])  # --note is required


def test_check_alerts_cli_exit_code(cli_db, pg_engine, capsys):
    from app.billing.cli import main
    assert main(["check-alerts"]) == 0
    sql(pg_engine, "INSERT INTO processed_webhook_events (provider, event_id, event_type, occurred_at, failures)"
                   " VALUES ('dodo', 'msg_y', 'refund.succeeded', now(), 5)")
    assert main(["check-alerts"]) == 1
    assert "webhook_failing" in capsys.readouterr().out
    sql(pg_engine, "TRUNCATE processed_webhook_events")
