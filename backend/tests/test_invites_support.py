"""Step 5: personal invites with the per-user quota enforced in Postgres (incl. the 11th
invite under concurrency), downloads history (re-download, delete now), support tickets,
and user A never seeing user B's downloads, invites or tickets."""

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.auth.invites import generate_code, hash_code
from tests.conftest import TABLES, fixture_text
from tests.test_admin_security import make_user
from tests.test_auth_signin import consent, csrf, post, scalar


@pytest.fixture(autouse=True)
def _clean(request):
    yield
    if "pg_engine" in request.fixturenames:
        with request.getfixturevalue("pg_engine").begin() as conn:
            conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))


def browser_for(new_browser, uid):
    b = new_browser()
    assert b.post(f"/test/login/{uid}").status_code == 200
    b.headers.update(csrf(b))
    return b


@pytest.fixture
def ada(new_browser, pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    return browser_for(new_browser, uid), uid


def create_invite(conn, uid, email, limit=10):
    code = generate_code()
    return conn.execute(text("SELECT create_user_invite(:u, :n, :h, :hint, :e, :x)"), {
        "u": uid, "n": limit, "h": hash_code(code), "hint": code[-4:], "e": email,
        "x": datetime.now(UTC) + timedelta(days=30)}).scalar_one()


def used(pg_engine, uid):
    return scalar(pg_engine, "SELECT invites_created FROM users WHERE id = :u", u=uid)


# --- the quota, in Postgres ----------------------------------------------------------------------


def test_the_eleventh_invite_is_refused(pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    with pg_engine.begin() as conn:
        for i in range(10):
            create_invite(conn, uid, f"friend{i}@example.org")
    with pytest.raises(DBAPIError, match="invite_limit"), pg_engine.begin() as conn:
        create_invite(conn, uid, "eleven@example.org")
    assert used(pg_engine, uid) == 10
    assert scalar(pg_engine, "SELECT count(*) FROM invites WHERE created_by = :u", u=uid) == 10


def test_the_eleventh_invite_is_refused_under_concurrency(pg_url, pg_engine):
    """25 requests at once, each on its own connection: exactly 10 invites exist after."""
    uid = make_user(pg_engine, "ada@example.com")
    engine = create_engine(pg_url, pool_size=25, max_overflow=0)
    start, results = threading.Barrier(25), []

    def attempt(i):
        start.wait()
        try:
            with engine.begin() as conn:
                create_invite(conn, uid, f"friend{i}@example.org")
            results.append("ok")
        except DBAPIError as exc:
            results.append("limit" if "invite_limit" in str(exc.orig) else repr(exc))

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine.dispose()
    assert sorted(results) == ["limit"] * 15 + ["ok"] * 10
    assert used(pg_engine, uid) == 10
    assert scalar(pg_engine, "SELECT count(*) FROM invites WHERE created_by = :u", u=uid) == 10


def test_link_sign_ups_and_email_invites_share_the_quota_under_concurrency(pg_url, pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    engine = create_engine(pg_url, pool_size=20, max_overflow=0)
    start, ok = threading.Barrier(20), []

    def attempt(i):
        start.wait()
        try:
            with engine.begin() as conn:
                if i % 2:
                    ok.append(bool(conn.execute(text("SELECT take_invite_slot(:u, 10)"), {"u": uid}).scalar_one()))
                else:
                    create_invite(conn, uid, f"friend{i}@example.org")
                    ok.append(True)
        except DBAPIError:
            ok.append(False)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine.dispose()
    assert ok.count(True) == 10 and used(pg_engine, uid) == 10


def test_revoking_an_unused_invite_returns_the_slot_but_a_used_one_doesnt(pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    with pg_engine.begin() as conn:
        unused, redeemed = create_invite(conn, uid, "a@example.org"), create_invite(conn, uid, "b@example.org")
        conn.execute(text("UPDATE invites SET uses = 1 WHERE id = :i"), {"i": redeemed})
    with pg_engine.begin() as conn:
        assert conn.execute(text("SELECT revoke_user_invite(:u, :i)"), {"u": uid, "i": unused}).scalar_one()
        assert conn.execute(text("SELECT revoke_user_invite(:u, :i)"), {"u": uid, "i": redeemed}).scalar_one()
        assert not conn.execute(text("SELECT revoke_user_invite(:u, :i)"), {"u": uid, "i": unused}).scalar_one()
    assert used(pg_engine, uid) == 1  # only the unused one came back


def test_rt_app_cannot_act_for_someone_else_or_touch_the_counter(pg_engine):
    ada, eve = make_user(pg_engine, "ada@example.com"), make_user(pg_engine, "eve@example.com")

    def as_eve(conn):
        conn.execute(text("SET LOCAL ROLE rt_app"))
        conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(eve)})

    with pytest.raises(DBAPIError, match="not_allowed"), pg_engine.connect() as conn, conn.begin():
        as_eve(conn)
        create_invite(conn, ada, "x@example.org")
    with pytest.raises(ProgrammingError, match="permission denied"), pg_engine.connect() as conn, conn.begin():
        as_eve(conn)
        conn.execute(text("UPDATE users SET invites_created = 0 WHERE id = :u"), {"u": eve})
    with pytest.raises(ProgrammingError, match="permission denied"), pg_engine.connect() as conn, conn.begin():
        as_eve(conn)
        conn.execute(text("SELECT take_invite_slot(:u, 100)"), {"u": eve})
    with pg_engine.connect() as conn, conn.begin():  # their own invite, through the function, is fine
        as_eve(conn)
        create_invite(conn, eve, "x@example.org")
    assert used(pg_engine, eve) == 1 and used(pg_engine, ada) == 0


def test_the_database_caps_the_limit_at_100(pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET invites_created = 100 WHERE id = :u"), {"u": uid})
    with pytest.raises(DBAPIError, match="invite_limit"), pg_engine.begin() as conn:
        create_invite(conn, uid, "x@example.org", limit=10_000)


# --- the invites API -----------------------------------------------------------------------------


def test_send_list_and_revoke(ada, outbox, pg_engine):
    b, uid = ada
    res = b.post("/api/invites", json={"email": "Friend@Example.org "})
    assert res.status_code == 201 and res.json()["email"] == "f***@example.org" and res.json()["left"] == 9
    mail = outbox[-1]
    assert mail.to == "friend@example.org" and mail.link.endswith("/signup")
    assert "invited you" in mail.subject and not any("code" in line.lower() for line in mail.lines)

    page = b.get("/api/invites").json()
    assert (page["limit"], page["used"], page["left"]) == (10, 1, 9)
    [inv] = page["invitees"]
    assert (inv["via"], inv["email"], inv["status"], inv["can_revoke"]) == ("email", "f***@example.org", "sent", True)
    assert "friend@example.org" not in str(page)

    assert b.delete(f"/api/invites/{inv['id']}").status_code == 204
    after = b.get("/api/invites").json()
    assert after["used"] == 0 and after["invitees"][0]["status"] == "revoked"
    assert b.delete(f"/api/invites/{inv['id']}").status_code == 404


@pytest.mark.parametrize("email,code", [
    ("ada+again@example.com", "own_email"), ("x@mailinator.com", "disposable_email"), ("nope", None),
])
def test_send_refuses(ada, email, code):
    b, _ = ada
    res = b.post("/api/invites", json={"email": email})
    assert res.status_code == 422 and (code is None or res.json()["detail"] == code)


def test_send_refuses_members_and_duplicates(ada, pg_engine, outbox):
    b, uid = ada
    make_user(pg_engine, "member@example.org")
    assert b.post("/api/invites", json={"email": "member@example.org"}).json()["detail"] == "already_member"
    assert b.post("/api/invites", json={"email": "f@example.org"}).status_code == 201
    assert b.post("/api/invites", json={"email": "f@example.org"}).json()["detail"] == "already_invited"
    assert used(pg_engine, uid) == 1 and len(outbox) == 1


def test_send_past_the_quota_is_refused(ada, pg_engine, outbox):
    b, uid = ada
    with pg_engine.begin() as conn:
        for i in range(10):
            create_invite(conn, uid, f"friend{i}@example.org")
    res = b.post("/api/invites", json={"email": "eleven@example.org"})
    assert (res.status_code, res.json()["detail"]) == (409, "invite_limit")
    assert outbox == []


def test_a_failed_email_uses_no_slot(ada, pg_engine, monkeypatch):
    from app.api import invites as invites_api
    from app.auth.mailer import MailerError

    class Broken:
        def send(self, mail):
            raise MailerError("network")

    monkeypatch.setattr(invites_api, "get_mailer", lambda: Broken())
    b, uid = ada
    res = b.post("/api/invites", json={"email": "f@example.org"})
    assert (res.status_code, res.json()["detail"]) == (503, "email_unavailable")
    assert used(pg_engine, uid) == 0 and scalar(pg_engine, "SELECT count(*) FROM invites") == 0


def test_a_used_invite_cant_be_revoked(ada, pg_engine):
    b, uid = ada
    iid = b.post("/api/invites", json={"email": "f@example.org"}).json()["id"]
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE invites SET uses = 1 WHERE id = :i"), {"i": iid})
    assert b.delete(f"/api/invites/{iid}").json()["detail"] == "already_used"


def test_the_invited_friend_joins_without_a_code_and_the_reward_follows(ada, new_browser, notices, pg_engine,
                                                                       monkeypatch):
    monkeypatch.setenv("RT_INVITE_ONLY", "1")
    b, uid = ada
    b.post("/api/invites", json={"email": "friend@example.org"})
    friend = new_browser()
    step = post(friend, "/test/identity", {"provider": "github", "provider_account_id": "f-1",
                                           "verified_email": "friend@example.org"}).json()["next"]
    assert step == "invite"
    assert post(friend, "/api/auth/signup/invite", {}).json()["next"] == "consent"  # the bound invite
    assert post(friend, "/api/auth/signup/complete", consent(notices)).json() == {"next": "signed_in"}
    [inv] = b.get("/api/invites").json()["invitees"]
    assert (inv["via"], inv["status"], inv["can_revoke"]) == ("email", "joined", False)

    friend.headers.update(csrf(friend))
    resume = friend.post("/api/resume/parse", files={"file": ("r.txt", fixture_text("resume_analyst.txt"))}).json()
    jd = friend.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")}).json()
    aid = friend.post("/api/analyses", json={"resume": resume, "jd": jd}).json()["analysis_id"]
    friend.post("/api/tailor", json={"resume": resume, "jd": jd, "use_llm": False}, headers={"X-Analysis-Id": aid})
    page = b.get("/api/invites").json()
    assert page["invitees"][0]["status"] == "rewarded" and page["credits_earned"] == 1
    assert used(pg_engine, uid) == 1  # the email invite used the slot; joining didn't take another


def test_link_sign_ups_use_the_same_quota(ada, new_browser, notices, pg_engine, monkeypatch):
    from tests.test_referrals import join
    monkeypatch.setenv("RT_INVITE_ONLY", "1")
    b, uid = ada
    code = b.get("/api/invites").json()["code"]
    with pg_engine.begin() as conn:
        for i in range(9):
            create_invite(conn, uid, f"friend{i}@example.org")
    _, res = join(new_browser, notices, code, "tenth@example.org", referral_invite=True)
    assert res.json() == {"next": "signed_in"} and used(pg_engine, uid) == 10
    _, res = join(new_browser, notices, code, "eleventh@example.org", referral_invite=True)
    assert res.json()["detail"] == "no_invite"  # refused at the invite step, before any account exists
    assert scalar(pg_engine, "SELECT count(*) FROM users WHERE email = 'eleventh@example.org'") == 0
    assert used(pg_engine, uid) == 10
    page = b.get("/api/invites").json()
    assert page["left"] == 0 and any(i["via"] == "link" and i["email"] == "t***@example.org" for i in page["invitees"])


def test_users_never_see_each_others_invites(new_browser, pg_engine):
    a = browser_for(new_browser, make_user(pg_engine, "ada@example.com"))
    e = browser_for(new_browser, make_user(pg_engine, "eve@example.com"))
    iid = a.post("/api/invites", json={"email": "f@example.org"}).json()["id"]
    assert e.get("/api/invites").json()["invitees"] == []
    assert e.delete(f"/api/invites/{iid}").status_code == 404
    assert a.get("/api/invites").json()["invitees"][0]["status"] == "sent"


# --- downloads -----------------------------------------------------------------------------------


def paid_download(pg_engine, uid, b, *, days_ago=0):
    resume = b.post("/api/resume/parse", files={"file": ("r.txt", fixture_text("resume_analyst.txt"))}).json()
    with pg_engine.begin() as conn:
        aid = conn.execute(text(
            "INSERT INTO analyses (user_id, idempotency_key, resume, jd, inputs_sha256, usable_until, job_title, company)"
            " VALUES (:u, :k, CAST(:r AS jsonb), '{}', 'x', now(), 'Senior Analyst', 'Acme') RETURNING id"),
            {"u": uid, "k": uuid.uuid4().hex, "r": __import__("json").dumps(resume)}).scalar_one()
        return conn.execute(text(
            "INSERT INTO downloads (user_id, analysis_id, format, paid_with, credits, final_resume, created_at)"
            " VALUES (:u, :a, 'pdf', 'credit', 1, CAST(:r AS jsonb), now() - make_interval(days => :d)) RETURNING id"),
            {"u": uid, "a": aid, "r": __import__("json").dumps(resume), "d": days_ago}).scalar_one()


def test_history_redownload_and_delete_now(ada, pg_engine):
    b, uid = ada
    did = paid_download(pg_engine, uid, b)
    balance = scalar(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=uid)
    [item] = b.get("/api/downloads").json()["items"]
    assert (item["job_title"], item["company"], item["format"], item["available"]) == ("Senior Analyst", "Acme", "pdf", True)
    assert item["file_name"].endswith("_tailored.pdf")
    link = b.post(f"/api/downloads/{did}/link").json()
    assert link["url"].startswith("/api/downloads/file/")
    f = b.get(link["url"])
    assert f.status_code == 200 and f.headers["content-type"] == "application/pdf"
    assert scalar(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=uid) == balance  # free
    assert scalar(pg_engine, "SELECT count(*) FROM downloads WHERE user_id = :u", u=uid) == 1  # no new row

    assert b.delete(f"/api/downloads/{did}").status_code == 204
    assert b.get("/api/downloads").json()["items"][0]["available"] is False
    assert b.post(f"/api/downloads/{did}/link").json()["detail"] == "file_expired"
    assert b.get(link["url"]).status_code == 410  # the old link dies with the file
    assert scalar(pg_engine, "SELECT credits FROM downloads WHERE id = :d", d=did) == 1  # billing record stays


def test_expires_on_follows_the_retention_setting(ada, pg_engine):
    b, uid = ada
    paid_download(pg_engine, uid, b, days_ago=2)
    [item] = b.get("/api/downloads").json()["items"]
    made, expires = datetime.fromisoformat(item["created_at"]), datetime.fromisoformat(item["expires_at"])
    assert expires - made == timedelta(days=7)


def test_purge_clears_expired_files(ada, pg_engine):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.billing.config import load_billing_config
    from app.billing.retention import purge_expired
    b, uid = ada
    old, new = paid_download(pg_engine, uid, b, days_ago=8), paid_download(pg_engine, uid, b)
    engine = create_async_engine(pg_engine.url.render_as_string(hide_password=False))
    asyncio.run(purge_expired(async_sessionmaker(engine, expire_on_commit=False), load_billing_config()))
    asyncio.run(engine.dispose())
    available = {i["id"]: i["available"] for i in b.get("/api/downloads").json()["items"]}
    assert available == {str(old): False, str(new): True}


def test_users_never_see_each_others_downloads(new_browser, pg_engine):
    a_id = make_user(pg_engine, "ada@example.com")
    a = browser_for(new_browser, a_id)
    e = browser_for(new_browser, make_user(pg_engine, "eve@example.com"))
    did = paid_download(pg_engine, a_id, a)
    link = a.post(f"/api/downloads/{did}/link").json()["url"]
    assert e.get("/api/downloads").json()["items"] == []
    assert e.post(f"/api/downloads/{did}/link").status_code == 404
    assert e.delete(f"/api/downloads/{did}").status_code == 404
    assert e.get(link).status_code == 404  # a leaked link is still only the payer's
    assert a.get("/api/downloads").json()["items"][0]["available"] is True


# --- support -------------------------------------------------------------------------------------


def test_contact_form_and_my_tickets(ada, new_browser, pg_engine):
    b, uid = ada
    res = b.post("/api/support/tickets", json={"category": "support", "subject": " Can't download ",
                                               "body": "The PDF button spins."})
    assert res.status_code == 201 and res.json()["status"] == "open" and res.json()["subject"] == "Can't download"
    assert [t["subject"] for t in b.get("/api/support/tickets").json()] == ["Can't download"]
    assert scalar(pg_engine, "SELECT email FROM support_tickets") == "ada@example.com"
    e = browser_for(new_browser, make_user(pg_engine, "eve@example.com"))
    assert e.get("/api/support/tickets").json() == []


@pytest.mark.parametrize("body", [
    {"category": "spam", "subject": "x", "body": "y"}, {"category": "support", "subject": "  ", "body": "y"},
    {"category": "support", "subject": "x" * 151, "body": "y"}, {"category": "support", "subject": "x", "body": "y" * 5001},
])
def test_ticket_validation(ada, body):
    b, _ = ada
    assert b.post("/api/support/tickets", json=body).status_code == 422


def test_a_fabrication_report_can_point_at_my_tailoring_only(ada, new_browser, pg_engine):
    b, uid = ada
    with pg_engine.begin() as conn:
        mine = conn.execute(text("INSERT INTO analyses (user_id, idempotency_key, resume, jd, inputs_sha256, usable_until)"
                                 " VALUES (:u, 'k', '{}', '{}', 'x', now()) RETURNING id"), {"u": uid}).scalar_one()
    eve = make_user(pg_engine, "eve@example.com")
    with pg_engine.begin() as conn:
        theirs = conn.execute(text("INSERT INTO analyses (user_id, idempotency_key, resume, jd, inputs_sha256, usable_until)"
                                   " VALUES (:u, 'k', '{}', '{}', 'x', now()) RETURNING id"), {"u": eve}).scalar_one()
    body = {"category": "fabrication_report", "subject": "Added a tool", "body": "It says Tableau; I never used it."}
    assert b.post("/api/support/tickets", json={**body, "analysis_id": str(mine)}).status_code == 201
    assert b.post("/api/support/tickets", json={**body, "analysis_id": str(theirs)}).status_code == 404


def test_support_is_rate_limited_per_user(ada):
    b, _ = ada
    body = {"category": "feedback", "subject": "Idea", "body": "More templates please."}
    codes = [b.post("/api/support/tickets", json=body).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]

