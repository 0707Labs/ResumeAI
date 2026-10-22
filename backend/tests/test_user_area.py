"""The signed-in user area (migration 0011, app/api/profile.py): onboarding, profile name,
job preferences, saved resumes, plan status, the dashboard, and the analysis metadata the
tailoring flow now records. Includes cross-user isolation under row-level security."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import fixture_text
from tests.test_admin_security import make_user
from tests.test_auth_signin import csrf, scalar


def browser_for(new_browser, uid):
    b = new_browser()
    assert b.post(f"/test/login/{uid}").status_code == 200
    b.headers.update(csrf(b))
    return b


@pytest.fixture
def ada(new_browser, pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    return browser_for(new_browser, uid), uid


def parsed(b):
    resume = b.post("/api/resume/parse", files={"file": ("r.txt", fixture_text("resume_analyst.txt"))}).json()
    jd = b.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")}).json()
    return resume, jd


# --- onboarding and profile ----------------------------------------------------------------------


def test_new_users_onboard_once(ada):
    b, _ = ada
    assert b.get("/api/me").json()["onboarded"] is False
    assert b.patch("/api/profile", json={"name": "  Ada   Lovelace "}).status_code == 204
    assert b.post("/api/profile/onboarded").status_code == 204
    me = b.get("/api/me").json()
    assert (me["onboarded"], me["name"]) == (True, "Ada Lovelace")
    assert b.post("/api/profile/onboarded").status_code == 204  # idempotent


def test_profile_name_is_validated(ada):
    b, _ = ada
    assert b.patch("/api/profile", json={"name": "   "}).status_code == 422
    assert b.patch("/api/profile", json={"name": "x" * 81}).status_code == 422


def test_profile_writes_need_csrf(new_browser, pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    b = new_browser()
    b.post(f"/test/login/{uid}")
    assert b.patch("/api/profile", json={"name": "Ada"}).status_code == 403


# --- job preferences -----------------------------------------------------------------------------


def test_preferences_round_trip_and_are_cleaned(ada):
    b, _ = ada
    empty = b.get("/api/profile/preferences").json()
    assert empty["target_roles"] == [] and empty["updated_at"] is None
    body = {"target_roles": [" Data  Analyst ", "data analyst", "BI Developer"], "seniority": "senior",
            "industries": ["Fintech"], "locations": ["Bengaluru", "Remote"], "work_modes": ["remote", "hybrid", "remote"],
            "employment_types": ["full_time"], "notice_period_days": 30}
    out = b.put("/api/profile/preferences", json=body).json()
    assert out["target_roles"] == ["Data Analyst", "BI Developer"]
    assert out["work_modes"] == ["remote", "hybrid"] and out["updated_at"]
    again = b.put("/api/profile/preferences", json={**body, "seniority": None, "notice_period_days": None}).json()
    assert again["seniority"] is None and again["target_roles"] == ["Data Analyst", "BI Developer"]


@pytest.mark.parametrize("bad", [
    {"seniority": "ceo"}, {"work_modes": ["moon"]}, {"employment_types": ["gig"]},
    {"notice_period_days": 400}, {"target_roles": ["x" * 81]}, {"locations": [f"city {i}" for i in range(11)]},
])
def test_preferences_reject_bad_values(ada, bad):
    b, _ = ada
    assert b.put("/api/profile/preferences", json=bad).status_code == 422


def test_database_also_rejects_bad_preferences(pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    for column, value in (("work_modes", "{moon}"), ("target_roles", "{\"\"}"), ("seniority", "ceo")):
        with pytest.raises(DBAPIError), pg_engine.begin() as conn:
            conn.execute(text(f"INSERT INTO job_preferences (user_id, {column}) VALUES (:u, :v)"),
                         {"u": uid, "v": value})


# --- saved resumes -------------------------------------------------------------------------------


def test_save_resume_first_is_default(ada):
    b, _ = ada
    resume, _ = parsed(b)
    first = b.post("/api/resumes", json={"resume": resume, "source": "upload", "file_name": "ada_cv.pdf"})
    assert first.status_code == 201
    assert (first.json()["title"], first.json()["is_default"], first.json()["version"]) == ("ada_cv", True, 1)
    second = b.post("/api/resumes", json={"resume": resume, "source": "paste", "title": "Short one"}).json()
    assert second["is_default"] is False
    listed = b.get("/api/resumes").json()
    assert [r["title"] for r in listed] == ["ada_cv", "Short one"]
    detail = b.get(f"/api/resumes/{first.json()['id']}").json()
    assert detail["resume"]["sections"] == resume["sections"]  # bullet ids preserved


def test_resume_limit(ada, pg_engine, monkeypatch):
    from app.api import profile
    monkeypatch.setattr(profile, "MAX_RESUMES", 1)
    b, _ = ada
    resume, _ = parsed(b)
    assert b.post("/api/resumes", json={"resume": resume, "source": "paste"}).status_code == 201
    res = b.post("/api/resumes", json={"resume": resume, "source": "paste"})
    assert (res.status_code, res.json()["detail"]) == (409, "resume_limit")


def test_resume_versions_are_never_updated(ada, pg_engine):
    b, uid = ada
    resume, _ = parsed(b)
    b.post("/api/resumes", json={"resume": resume, "source": "paste"})
    with pytest.raises(DBAPIError, match="never updated"), pg_engine.begin() as conn:
        conn.execute(text("UPDATE resume_versions SET source = 'edit' WHERE user_id = :u"), {"u": uid})


def test_a_version_must_belong_to_its_resumes_owner(ada, pg_engine):
    b, uid = ada
    other = make_user(pg_engine, "eve@example.com")
    resume, _ = parsed(b)
    rid = b.post("/api/resumes", json={"resume": resume, "source": "paste"}).json()["id"]
    with pytest.raises(DBAPIError, match="owner"), pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO resume_versions (resume_id, user_id, version, content, source)"
                          " VALUES (:r, :u, 2, '{}', 'edit')"), {"r": rid, "u": other})


def test_users_cannot_see_each_others_resumes_or_preferences(new_browser, pg_engine):
    a = browser_for(new_browser, make_user(pg_engine, "ada@example.com"))
    e = browser_for(new_browser, make_user(pg_engine, "eve@example.com"))
    resume, _ = parsed(a)
    rid = a.post("/api/resumes", json={"resume": resume, "source": "paste"}).json()["id"]
    a.put("/api/profile/preferences", json={"target_roles": ["Analyst"]})
    assert e.get(f"/api/resumes/{rid}").status_code == 404
    assert e.get("/api/resumes").json() == []
    assert e.get("/api/profile/preferences").json()["target_roles"] == []
    assert e.get("/api/dashboard").json()["has_resume"] is False


def test_account_deletion_removes_saved_resumes_and_preferences(ada, pg_engine):
    b, uid = ada
    resume, _ = parsed(b)
    b.post("/api/resumes", json={"resume": resume, "source": "paste"})
    b.put("/api/profile/preferences", json={"target_roles": ["Analyst"]})
    assert b.post("/api/account/delete", json={"confirm": True}).status_code == 204
    for table in ("resumes", "resume_versions", "job_preferences"):
        assert scalar(pg_engine, f"SELECT count(*) FROM {table} WHERE user_id = :u", u=uid) == 0


# --- plan ----------------------------------------------------------------------------------------


def test_plan_status_follows_the_download_order(ada, pg_engine):
    b, uid = ada
    plan = b.get("/api/plan").json()
    assert (plan["kind"], plan["credits"], plan["free_left"]) == ("free", 0, plan["free_allowance"])
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET credits_balance = 3 WHERE id = :u"), {"u": uid})
    assert b.get("/api/plan").json()["kind"] == "credits"
    with pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO passes (user_id, product_key, reference_id, starts_at, expires_at, analyses_cap)"
                          " VALUES (:u, 'job_hunt_pass', 'pay_x', now() - interval '1 day',"
                          " now() + interval '9 days 2 hours', 40)"), {"u": uid})
    plan = b.get("/api/plan").json()
    assert (plan["kind"], plan["pass_days_left"], plan["pass_downloads_left"], plan["credits"]) == ("pass", 10, 40, 3)


# --- dashboard and analysis metadata -------------------------------------------------------------


def test_dashboard_for_a_new_user(ada):
    b, _ = ada
    d = b.get("/api/dashboard").json()
    assert d["recent"] == [] and d["last_tip"] is None and d["plan"]["kind"] == "free"
    assert d["has_resume"] is False and d["has_preferences"] is False
    assert d["referrals"]["joined"] == 0 and d["referrals"]["invites_left"] == d["referrals"]["invites_per_user"]


def test_tailoring_records_metadata_for_the_dashboard(ada, pg_engine):
    b, uid = ada
    resume, jd = parsed(b)
    aid = b.post("/api/analyses", json={"resume": resume, "jd": jd}).json()["analysis_id"]
    head = {"X-Analysis-Id": aid}
    tailored = b.post("/api/tailor", json={"resume": resume, "jd": jd, "use_llm": False}, headers=head).json()
    scored = b.post("/api/ats/score", json={"resume": resume, "jd": jd, "tailored": tailored, "use_llm": False,
                                            "approved_only": False}, headers=head)
    assert scored.status_code == 200
    advice = b.post("/api/mentor", json={"resume": resume, "jd": jd, "use_llm": False}, headers=head).json()

    [recent] = b.get("/api/dashboard").json()["recent"]
    assert recent["id"] == aid and recent["status"] == "tailored"
    assert recent["job_title"] == jd["title"] and recent["company"] == jd["company"]
    assert recent["ats_before"] == round(scored.json()["before"]["total"], 1)
    assert recent["ats_after"] == round(scored.json()["after"]["total"], 1)
    tip = b.get("/api/dashboard").json()["last_tip"]
    assert tip["text"] == advice["actions"][0]["text"]


def test_no_metadata_without_a_matching_analysis(ada, pg_engine):
    b, uid = ada
    resume, jd = parsed(b)
    b.post("/api/ats/score", json={"resume": resume, "jd": jd, "use_llm": False})  # no X-Analysis-Id
    assert scalar(pg_engine, "SELECT count(*) FROM analyses WHERE user_id = :u", u=uid) == 0
    aid = b.post("/api/analyses", json={"resume": resume, "jd": jd}).json()["analysis_id"]
    other_jd = {**jd, "raw_text": jd["raw_text"] + " changed"}
    b.post("/api/ats/score", json={"resume": resume, "jd": other_jd, "use_llm": False}, headers={"X-Analysis-Id": aid})
    assert scalar(pg_engine, "SELECT ats_before FROM analyses WHERE id = :a", a=aid) is None


def test_purge_clears_the_mentor_tip(pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    with pg_engine.begin() as conn:
        aid = conn.execute(text(
            "INSERT INTO analyses (user_id, idempotency_key, resume, jd, inputs_sha256, usable_until, created_at,"
            " mentor_tip, job_title, ats_before) VALUES (:u, 'k', '{}', '{}', 'x', :old, :old, 'Lead with numbers',"
            " 'Analyst', 61.5) RETURNING id"), {"u": uid, "old": datetime.now(UTC) - timedelta(days=60)}).scalar_one()
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.billing.config import load_billing_config
    from app.billing.retention import purge_expired
    engine = create_async_engine(pg_engine.url.render_as_string(hide_password=False))
    asyncio.run(purge_expired(async_sessionmaker(engine, expire_on_commit=False), load_billing_config()))
    asyncio.run(engine.dispose())
    with pg_engine.connect() as conn:
        row = conn.execute(text("SELECT mentor_tip, job_title, ats_before, purged_at FROM analyses WHERE id = :a"),
                           {"a": aid}).one()
    assert row.mentor_tip is None and row.purged_at is not None
    assert (row.job_title, float(row.ats_before)) == ("Analyst", 61.5)  # metadata stays


@pytest.fixture(autouse=True)
def _clean(request):
    yield
    if "pg_engine" in request.fixturenames:
        from tests.conftest import TABLES
        with request.getfixturevalue("pg_engine").begin() as conn:
            conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))

