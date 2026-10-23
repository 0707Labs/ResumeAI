"""Step 8: the admin overview, integrations (never a secret value), the webhook log and
replay, quality counts, the config view, runtime plan flags and model choice, the
maintenance banner, and the stale-invite job."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.admin import counters
from app.admin import integrations as integ
from app.admin.quality import download_counts, tailor_counts
from app.api.billing import payment_provider
from app.auth.cli import expire_invites
from app.llm.client import ClaudeLLM
from app.models.tailor import ReviewStatus, Severity, TailoredResume
from tests.conftest import TABLES
from tests.test_admin_security import audit_rows, make_user, signed_in
from tests.test_auth_signin import scalar
from tests.test_billing_webhooks import make_payment
from tests.test_costs_revenue import analysis, run
from tests.test_llm_client import Out, StubClient, resp


@pytest.fixture(autouse=True)
def _clean(request):
    counters.take()
    yield
    counters.take()
    if "pg_engine" in request.fixturenames:
        with request.getfixturevalue("pg_engine").begin() as conn:
            conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))


def execute(pg_engine, sql, **params):
    with pg_engine.begin() as conn:
        return conn.execute(text(sql), params)


# --- overview -------------------------------------------------------------------------------------


def test_overview_kpis_funnel_and_who_sees_money(new_browser, pg_engine):
    admin, _ = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    support, _ = signed_in(new_browser, pg_engine, "support", "support@example.com")
    user, _ = signed_in(new_browser, pg_engine, "user", "plain@example.com")
    ada = make_user(pg_engine, "ada@example.com")
    aid = analysis(pg_engine, ada)
    execute(pg_engine, "UPDATE analyses SET tailored = '{}', llm_tailored = false, tailored_at = now() WHERE id = :a", a=aid)
    make_payment(pg_engine, ada)
    execute(pg_engine, "UPDATE payments SET status = 'paid', paid_at = now()")
    notice = execute(pg_engine, "INSERT INTO consent_notices (purpose, version, body_sha256, body_url, published_at)"
                     " VALUES ('waitlist', 'w1', 'x', '/privacy', now()) RETURNING id").scalar_one()
    execute(pg_engine, "INSERT INTO waitlist (email, source, notice_id) VALUES ('w@example.org', 'landing', :n)", n=notice)
    execute(pg_engine, "INSERT INTO daily_counters (day, name, count) VALUES (current_date, 'landing.view', 40)")

    assert user.get("/api/admin/overview").status_code == 403
    out = admin.get("/api/admin/overview", params={"days": 7}).json()
    assert out["users"]["total"] == 4 and out["users"]["new_7d"] == 4 and out["users"]["waitlist"] == 1
    assert out["users"]["paid"] == 1 and out["tailorings"] == {"d7": 1, "d30": 1}
    assert out["funnel"] == {"landing_views": 40, "signups": 4, "first_tailoring": 1, "downloaded": 0, "paid": 1}
    assert len(out["series"]) == 7 and out["series"][-1]["signups"] == 4
    assert out["revenue"] is not None and out["costs"] is not None

    limited = support.get("/api/admin/overview").json()
    assert limited["revenue"] is None and limited["costs"] is None
    assert all(d["revenue_usd"] is None and d["cost_usd"] is None for d in limited["series"])
    csv = support.get("/api/admin/overview/export.csv", params={"days": 3})
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0].strip() == "day,signups"  # no money columns for support
    assert admin.get("/api/admin/overview/export.csv").text.splitlines()[0].strip() == "day,signups,revenue_usd,cost_usd"


def test_landing_views_are_counted_without_a_session(new_browser, pg_engine):
    anon = new_browser()
    for _ in range(3):
        assert anon.post("/api/metrics/landing-view").status_code == 204
    assert counters.take() == {(datetime.now(UTC).date(), "landing.view"): 3}
    counters.bump("landing.view", 2)
    counters.bump("Not A Name!")  # refused, never stored
    assert run(pg_engine, counters.flush) == 1
    assert scalar(pg_engine, "SELECT count FROM daily_counters WHERE name = 'landing.view'") == 2


def test_resume_parse_results_are_counted(client):
    assert client.post("/api/resume/parse", files={"file": ("r.exe", b"MZ...")}).status_code == 415
    [(_, name)] = counters.take()
    assert name == "resume_parse.failed.415"


# --- integrations -------------------------------------------------------------------------------

# Random secret parts (so a match can't be a coincidence with names in the response), each
# behind whatever fixed prefix the real value would have.
RAND = {k: uuid.uuid4().hex for k in ("ANTHROPIC_API_KEY", "DODO_API_KEY", "DODO_WEBHOOK_SECRET", "AWS_ACCESS_KEY_ID",
                                      "AWS_SECRET_ACCESS_KEY", "GOOGLE_CLIENT_SECRET", "RT_SLACK_WEBHOOK_URL")}
PREFIX = {"ANTHROPIC_API_KEY": "sk-ant-api03-", "DODO_WEBHOOK_SECRET": "whsec_", "GOOGLE_CLIENT_SECRET": "GOCSPX-",
          "RT_SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/"}
SECRETS = {k: PREFIX.get(k, "") + v for k, v in RAND.items()}


def _leaks(body: str, value: str) -> str | None:
    """The first 5-character run of the secret that appears in the response, if any."""
    return next((value[i:i + 5] for i in range(len(value) - 4) if value[i:i + 5] in body), None)


def test_integrations_never_return_secret_values(new_browser, pg_engine, monkeypatch):
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "1234-abc.apps.googleusercontent.com")
    monkeypatch.setenv("RT_MAILER", "outbox")
    admin, _ = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    boss, _ = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    support, _ = signed_in(new_browser, pg_engine, "support", "support@example.com")
    assert support.get("/api/admin/integrations").status_code == 403

    for who in (admin, boss):
        body = who.get("/api/admin/integrations").text
        for name, value in RAND.items():
            leaked = _leaks(body.replace("…" + value[-4:], ""), value)
            assert leaked is None, (name, leaked, body[max(0, body.find(leaked or "") - 80):body.find(leaked or "") + 40])
    cards = {c["name"]: c for c in admin.get("/api/admin/integrations").json()}
    assert all(s["hint"] is None for c in cards.values() for s in c["secrets"])  # hints are superadmin-only
    assert cards["anthropic"]["status"] == "configured" and cards["error_monitoring"]["status"] == "not_configured"
    assert cards["google"]["facts"]["redirect_uri"].endswith("/api/auth/google/callback")
    boss_cards = {c["name"]: c for c in boss.get("/api/admin/integrations").json()}
    hints = {s["name"]: s["hint"] for c in boss_cards.values() for s in c["secrets"]}
    assert hints["ANTHROPIC_API_KEY"] == "…" + SECRETS["ANTHROPIC_API_KEY"][-4:] and hints["RT_DATABASE_URL"] is None
    assert hints["RT_SLACK_WEBHOOK_URL"] is None  # a URL is never hinted


def test_a_health_check_is_stored_audited_and_keeps_the_last_success(new_browser, pg_engine, monkeypatch):
    admin, _ = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    support, _ = signed_in(new_browser, pg_engine, "support", "support@example.com")
    results = iter([integ.CheckResult("healthy", detail={"model": "m"}), integ.CheckResult("failing", "http_401")])

    async def fake(db):
        return next(results)
    monkeypatch.setitem(integ.CHECKS, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key-long-enough-0000")

    assert support.post("/api/admin/integrations/anthropic/check").status_code == 403
    first = admin.post("/api/admin/integrations/anthropic/check").json()
    assert first["status"] == "healthy" and first["last_ok_at"] is not None
    second = admin.post("/api/admin/integrations/anthropic/check").json()
    assert second["status"] == "failing" and second["error_code"] == "http_401"
    assert second["last_ok_at"] == first["last_ok_at"]  # still shows when it last worked
    assert admin.post("/api/admin/integrations/nope/check").status_code == 404
    assert [r["action"] for r in audit_rows(pg_engine, "anthropic")] == ["integrations.check"] * 2


def test_the_database_check_reports_version_and_migration(new_browser, pg_engine):
    admin, _ = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    out = admin.post("/api/admin/integrations/database/check").json()
    assert out["status"] == "healthy" and out["check_detail"]["migration"] == "0016_admin_ops"


# --- webhook log and replay ---------------------------------------------------------------------


def test_a_failed_webhook_replays_once_and_its_payload_is_never_listed(new_browser, pg_engine, api_app):
    api_app.dependency_overrides[payment_provider] = lambda: SimpleNamespace(name="dodo", mode="test")
    admin, _ = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    support, _ = signed_in(new_browser, pg_engine, "support", "support@example.com")
    execute(pg_engine, "INSERT INTO processed_webhook_events (provider, event_id, event_type, occurred_at, failures,"
            " last_error, payload) VALUES ('dodo', 'msg_1', 'something.brand_new', now(), 2, 'KeyError',"
            " CAST(:p AS jsonb))", p=json.dumps({"customer": {"email": "secret-buyer@example.com"}}))

    listed = admin.get("/api/admin/webhooks", params={"status": "failing"})
    assert "secret-buyer" not in listed.text
    [item] = listed.json()["items"]
    assert item["status"] == "failing" and item["replayable"] and item["failures"] == 2
    assert support.post("/api/admin/webhooks/msg_1/replay", json={"reason": "retry"}).status_code == 403
    assert admin.post("/api/admin/webhooks/msg_1/replay", json={"reason": "fixed"}).json() == {"outcome": "ignored"}
    assert scalar(pg_engine, "SELECT payload IS NULL AND outcome = 'ignored' FROM processed_webhook_events") is True
    assert admin.post("/api/admin/webhooks/msg_1/replay", json={"reason": "again"}).status_code == 409
    assert [r["action"] for r in audit_rows(pg_engine, "msg_1")] == ["billing.webhook_replay"]


# --- quality ------------------------------------------------------------------------------------


def _tailored(flags_and_reviews):
    bullets = []
    for i, (flagged, review) in enumerate(flags_and_reviews):
        flags = [{"kind": "new_claim", "detail": "check", "severity": Severity.WARN}] if flagged else []
        bullets.append({"id": f"t{i}", "text": "Did a thing", "source_bullet_ids": ["b1"], "change_type": "reword",
                        "verification": {"flags": flags}, "review": review,
                        "rejected_attempts": [{"text": "x", "flags": []}] if i == 0 else []})
    return TailoredResume.model_validate({"bullets": bullets})


def test_quality_counts_come_from_the_verifier_and_the_review():
    t = _tailored([(True, ReviewStatus.APPROVED), (False, ReviewStatus.APPROVED), (True, ReviewStatus.REJECTED),
                   (False, ReviewStatus.PENDING)])
    assert tailor_counts(t) == {"bullets_generated": 4, "bullets_blocked": 1, "bullets_flagged": 2}
    assert download_counts(t) == {"bullets_approved": 2, "bullets_rejected": 1, "flag_overrides": 1}


def test_quality_view(new_browser, pg_engine):
    admin, _ = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    support, _ = signed_in(new_browser, pg_engine, "support", "support@example.com")
    uid = make_user(pg_engine, "ada@example.com")
    for before, after, counts in ((60, 75, (10, 2, 3, 6, 2, 1)), (70, 68, (4, 0, 1, None, None, None))):
        a = analysis(pg_engine, uid)
        execute(pg_engine, "UPDATE analyses SET ats_before = :b, ats_after = :f, bullets_generated = :g,"
                " bullets_blocked = :bl, bullets_flagged = :fl, bullets_approved = :ap, bullets_rejected = :rj,"
                " flag_overrides = :ov WHERE id = :a", a=a, b=before, f=after, g=counts[0], bl=counts[1], fl=counts[2],
                ap=counts[3], rj=counts[4], ov=counts[5])
    execute(pg_engine, "INSERT INTO daily_counters (day, name, count) VALUES (current_date, 'resume_parse.ok', 18),"
            " (current_date, 'resume_parse.failed.422', 2), (current_date, 'resume_parse.warning.tables_detected', 5)")
    execute(pg_engine, "INSERT INTO support_tickets (user_id, email, category, subject, body) VALUES"
            " (:u, 'ada@example.com', 'fabrication_report', 'Invented a metric', 'It said 40%')", u=uid)

    assert support.get("/api/admin/quality").status_code == 403
    out = admin.get("/api/admin/quality").json()
    v = out["verifier"]
    assert v["totals"]["bullets_generated"] == 14 and v["totals"]["analyses_tailored"] == 2
    assert v["totals"]["analyses_downloaded"] == 1
    assert v["rates"] == {"flagged": round(4 / 14, 4), "blocked": round(2 / 16, 4), "override": round(1 / 6, 4)}
    assert out["parsing"] == {"attempts": 20, "ok": 18, "failed": {"422": 2}, "failure_rate": 0.1,
                              "warnings": {"tables_detected": 5}}
    lift = {b["label"]: b["count"] for b in out["ats_lift"]["buckets"]}
    assert lift["below 0"] == 1 and lift["11 to 20"] == 1 and out["ats_lift"]["median"] == 6.5
    [report] = out["fabrication_reports"]
    assert report["subject"] == "Invented a metric" and "body" not in report


# --- settings: plans, models, banner, config view -----------------------------------------------


def test_plan_flags_change_what_is_sold(new_browser, pg_engine):
    boss, _ = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    anon = new_browser()
    before = anon.get("/api/billing/plans").json()
    assert boss.put("/api/admin/settings/free_analyses_per_month", json={"value": 5, "reason": "promo"}).status_code == 200
    assert boss.put("/api/admin/settings/pro_enabled", json={"value": False, "reason": "not yet"}).status_code == 200
    after = anon.get("/api/billing/plans").json()
    assert after["free_analyses_per_month"] == 5 != before["free_analyses_per_month"]
    assert "pro_monthly" not in {p["key"] for p in after["plans"]}


def test_model_choice_is_allowlisted_and_used(new_browser, pg_engine, pg_url, monkeypatch):
    from app.billing import costs
    from app.llm import models

    boss, _ = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    bad = {"tailor": {"model": "gpt-4", "max_tokens": 4000, "effort": "low"}}
    assert boss.put("/api/admin/settings/llm_models", json={"value": bad, "reason": "try"}).json()["detail"] == "model_not_allowed"
    shape = {"tailor": {"model": "claude-sonnet-5-5", "max_tokens": 100, "effort": "low"}}
    assert boss.put("/api/admin/settings/llm_models", json={"value": shape, "reason": "x" * 3}).status_code == 422
    good = {"tailor": {"model": "claude-sonnet-5-5", "max_tokens": 8000, "effort": "low"}}
    out = boss.put("/api/admin/settings/llm_models", json={"value": good, "reason": "cheaper tailoring"}).json()
    assert out["values"]["llm_models"] == good

    monkeypatch.setenv("RT_DATABASE_URL", pg_url)
    costs._engine.cache_clear()
    models.clear_cache()
    try:
        stub = StubClient(resp())
        ClaudeLLM(client=stub, step_models=models.for_step).parse(system="s", user="u", schema=Out)
        assert stub.kwargs["model"] == "claude-opus-5-5" and stub.kwargs["max_tokens"] == 16000  # Out: not a step

        class _LLMTailored(Out):
            pass
        ClaudeLLM(client=stub, step_models=models.for_step).parse(system="s", user="u", schema=_LLMTailored)
        call = stub.kwargs
        assert (call["model"], call["max_tokens"], call["output_config"]) == ("claude-sonnet-5-5", 8000, {"effort": "low"})
    finally:
        costs._engine.cache_clear()
        models.clear_cache()


def test_the_maintenance_banner_reaches_every_visitor(new_browser, pg_engine):
    boss, _ = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    note = "Payments are down for 10 minutes."
    assert boss.put("/api/admin/settings/maintenance_banner", json={"value": note, "reason": "dodo outage"}).status_code == 200
    assert new_browser().get("/api/auth/config").json()["maintenance_banner"] == note


def test_config_view(new_browser, pg_engine):
    admin, _ = signed_in(new_browser, pg_engine, "admin", "admin@example.com")
    support, _ = signed_in(new_browser, pg_engine, "support", "support@example.com")
    assert support.get("/api/admin/config").status_code == 403
    out = admin.get("/api/admin/config").json()
    assert {p["kind"] for p in out["products"]} >= {"credit_pack", "pass"}
    assert out["retention"]["analysis_days"] > 0 and "claude-opus-5-5" in out["llm_prices"]


def test_audit_log_filters_by_date(new_browser, pg_engine):
    boss, boss_id = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    started = datetime.now(UTC) - timedelta(seconds=1)
    boss.put("/api/admin/settings/maintenance_banner", json={"value": "hi", "reason": "test"})
    mine = {"target_id": "maintenance_banner", "action": "settings.update", "actor_id": str(boss_id)}
    assert len(boss.get("/api/admin/audit", params={**mine, "since": started.isoformat()}).json()["entries"]) == 1
    assert boss.get("/api/admin/audit", params={**mine, "until": started.isoformat()}).json()["entries"] == []


# --- the stale-invite job -----------------------------------------------------------------------


def test_expired_unused_invites_give_their_slot_back(pg_engine, pg_url):
    uid = make_user(pg_engine, "ada@example.com")
    execute(pg_engine, "UPDATE users SET invites_created = 3 WHERE id = :u", u=uid)
    for email, expires, uses in (("old@example.org", "now() - interval '1 day'", 0),
                                 ("used@example.org", "now() - interval '1 day'", 1),
                                 ("fresh@example.org", "now() + interval '5 days'", 0)):
        execute(pg_engine, "INSERT INTO invites (code_hash, code_hint, email, created_by, kind, max_uses, uses, expires_at)"
                f" VALUES (:h, 'ABCD', :e, :u, 'personal', 1, :n, {expires})", h=uuid.uuid4().hex, e=email, u=uid, n=uses)
    engine = create_engine(pg_url)
    try:
        with Session(engine) as db:
            assert expire_invites(db) == 1
            assert expire_invites(db) == 0  # idempotent
    finally:
        engine.dispose()
    assert scalar(pg_engine, "SELECT invites_created FROM users WHERE email = 'ada@example.com'") == 2
    assert scalar(pg_engine, "SELECT email FROM invites WHERE revoked_at IS NOT NULL") == "old@example.org"
