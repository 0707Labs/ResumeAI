"""Step 6: the admin console. Users (list, CSV, detail, audited actions), invite codes and
the waitlist, the support inbox, and runtime settings for invites and referrals.
Includes the spec's checks: support can't adjust credits, credit adjustments always go
through the ledger with an audit entry, bulk codes are unique, and redemption is atomic
and refuses expired, revoked, exhausted and email-locked codes."""

import json
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.auth.invites import ALPHABET, hash_code, normalize
from tests.conftest import TABLES, fixture_text
from tests.test_admin_security import audit_rows, make_user, signed_in
from tests.test_auth_signin import consent, csrf, post, scalar


@pytest.fixture(autouse=True)
def _clean(request):
    yield
    if "pg_engine" in request.fixturenames:
        with request.getfixturevalue("pg_engine").begin() as conn:
            conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))


@pytest.fixture
def admin(new_browser, pg_engine):
    return signed_in(new_browser, pg_engine, "admin", "admin@example.com")


@pytest.fixture
def support(new_browser, pg_engine):
    return signed_in(new_browser, pg_engine, "support", "support@example.com")


def ledger(pg_engine, uid):
    with pg_engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(
            "SELECT delta, reason, note, balance_after FROM credit_transactions WHERE user_id = :u ORDER BY id"), {"u": uid})]


# --- users: list, CSV, detail --------------------------------------------------------------------


def test_list_searches_filters_sorts_and_pages(admin, pg_engine):
    browser, _ = admin
    ids = [make_user(pg_engine, f"user{i}@example.com") for i in range(5)]
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET credits_balance = 7 WHERE id = :u"), {"u": ids[0]})
        conn.execute(text("UPDATE users SET status = 'suspended' WHERE id = :u"), {"u": ids[1]})
    page = browser.get("/api/admin/users", params={"page_size": 2, "sort": "email", "direction": "asc"}).json()
    assert page["total"] == 6 and [r["email"] for r in page["items"]] == ["admin@example.com", "user0@example.com"]
    assert browser.get("/api/admin/users", params={"q": "USER3"}).json()["items"][0]["email"] == "user3@example.com"
    assert [r["email"] for r in browser.get("/api/admin/users", params={"plan": "credits"}).json()["items"]] == ["user0@example.com"]
    assert [r["status"] for r in browser.get("/api/admin/users", params={"status": "suspended"}).json()["items"]] == ["suspended"]
    assert browser.get("/api/admin/users", params={"role": "admin"}).json()["total"] == 1
    assert browser.get("/api/admin/users", params={"sort": "password"}).status_code == 422


def test_csv_export_is_defused_and_audited(admin, pg_engine):
    browser, admin_id = admin
    uid = make_user(pg_engine, "evil@example.com")
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET name = '=HYPERLINK(\"x\")' WHERE id = :u"), {"u": uid})
    res = browser.get("/api/admin/users/export.csv")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK" in res.text and "\n=HYPERLINK" not in res.text
    with pg_engine.connect() as conn:
        actions = conn.execute(text("SELECT action, actor_id FROM admin_audit_log WHERE action = 'users.export'")).all()
    assert [(a, actor) for a, actor in actions] == [("users.export", admin_id)]


def test_detail_is_metadata_only_and_billing_needs_billing_read(admin, support, pg_engine):
    a, _ = admin
    s, _ = support
    uid = make_user(pg_engine, "ada@example.com")
    resume = {"name": "Ada", "sections": [{"entries": [{"bullets": [{"text": "SECRET BULLET TEXT"}]}]}]}
    with pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO analyses (user_id, idempotency_key, resume, jd, inputs_sha256, usable_until, job_title)"
                          " VALUES (:u, 'k', CAST(:r AS jsonb), '{\"raw_text\": \"SECRET JD TEXT\"}', 'x', now(), 'Analyst')"),
                     {"u": uid, "r": json.dumps(resume)})
    full = a.get(f"/api/admin/users/{uid}")
    assert full.status_code == 200
    body = full.json()
    assert body["tailorings"][0]["job_title"] == "Analyst" and body["plan"]["kind"] == "free" and body["ledger"] == []
    assert "SECRET" not in full.text
    assert body["can"] == {"users_write": True, "credits_adjust": True, "passes_grant": True, "users_delete": False}
    limited = s.get(f"/api/admin/users/{uid}").json()
    assert limited["plan"] is None and limited["ledger"] is None and limited["payments"] is None
    assert limited["can"] == {"users_write": False, "credits_adjust": False, "passes_grant": False, "users_delete": False}
    assert a.get(f"/api/admin/users/{uuid.uuid4()}").status_code == 404


# --- users: actions ------------------------------------------------------------------------------


def test_credit_adjustments_go_through_the_ledger_and_are_audited(admin, pg_engine):
    browser, admin_id = admin
    uid = make_user(pg_engine, "ada@example.com")
    res = browser.post(f"/api/admin/users/{uid}/credits", json={"delta": 5, "reason": "goodwill for outage"})
    assert res.json() == {"credits_balance": 5}
    assert browser.post(f"/api/admin/users/{uid}/credits", json={"delta": -2, "reason": "duplicate grant"}).json() == {
        "credits_balance": 3}
    assert ledger(pg_engine, uid) == [
        {"delta": 5, "reason": "admin_adjust", "note": "goodwill for outage", "balance_after": 5},
        {"delta": -2, "reason": "admin_adjust", "note": "duplicate grant", "balance_after": 3}]
    rows = audit_rows(pg_engine, uid)
    assert [(r["action"], r["actor_id"], r["after"]["delta"]) for r in rows] == [
        ("credits.adjust", admin_id, 5), ("credits.adjust", admin_id, -2)]
    assert rows[0]["after"]["ledger_key"].startswith("admin:")
    # Never below zero: refused, and neither a ledger row nor an audit entry is written.
    res = browser.post(f"/api/admin/users/{uid}/credits", json={"delta": -10, "reason": "too much"})
    assert (res.status_code, res.json()["detail"]) == (409, "insufficient_credits")
    assert len(ledger(pg_engine, uid)) == 2 and len(audit_rows(pg_engine, uid)) == 2
    assert browser.post(f"/api/admin/users/{uid}/credits", json={"delta": 3, "reason": "x"}).status_code == 422  # reason


def test_support_cannot_adjust_credits_grant_passes_or_suspend(support, pg_engine):
    browser, _ = support
    uid = make_user(pg_engine, "ada@example.com")
    for path, body in [("credits", {"delta": 5, "reason": "please"}), ("pass", {"reason": "please"}),
                       ("suspend", {"reason": "please"}), ("sign-out", {"reason": "please"})]:
        assert browser.post(f"/api/admin/users/{uid}/{path}", json=body).status_code == 403, path
    assert ledger(pg_engine, uid) == [] and audit_rows(pg_engine, uid) == []


def test_suspend_ends_sessions_and_unsuspend_restores(admin, new_browser, pg_engine):
    browser, _ = admin
    uid = make_user(pg_engine, "ada@example.com")
    ada = new_browser()
    ada.post(f"/test/login/{uid}")
    assert ada.get("/api/me").status_code == 200
    assert browser.post(f"/api/admin/users/{uid}/suspend", json={"reason": "chargeback fraud"}).status_code == 204
    assert ada.get("/api/me").status_code == 401  # session gone
    assert scalar(pg_engine, "SELECT status FROM users WHERE id = :u", u=uid) == "suspended"
    assert browser.post(f"/api/admin/users/{uid}/unsuspend", json={"reason": "resolved"}).status_code == 204
    assert [r["action"] for r in audit_rows(pg_engine, uid)] == ["users.suspend", "users.unsuspend"]
    assert audit_rows(pg_engine, uid)[0]["after"]["sessions_ended"] == 1


def test_grant_pass_and_force_sign_out(admin, new_browser, pg_engine):
    browser, _ = admin
    uid = make_user(pg_engine, "ada@example.com")
    out = browser.post(f"/api/admin/users/{uid}/pass", json={"reason": "beta tester", "days": 14}).json()
    starts, ends = datetime.fromisoformat(out["starts_at"]), datetime.fromisoformat(out["expires_at"])
    assert ends - starts == timedelta(days=14)
    assert scalar(pg_engine, "SELECT reference_id FROM passes WHERE user_id = :u", u=uid).startswith("admin:")
    ada = new_browser()
    ada.post(f"/test/login/{uid}")
    assert browser.post(f"/api/admin/users/{uid}/sign-out", json={"reason": "lost laptop"}).status_code == 204
    assert ada.get("/api/me").status_code == 401
    assert [r["action"] for r in audit_rows(pg_engine, uid)] == ["passes.grant", "users.sign_out"]


def test_staff_accounts_and_your_own_are_off_limits(admin, new_browser, pg_engine):
    browser, admin_id = admin
    other_admin = make_user(pg_engine, "other-admin@example.com", "admin")
    assert browser.post(f"/api/admin/users/{other_admin}/suspend", json={"reason": "test"}).status_code == 403
    assert browser.post(f"/api/admin/users/{admin_id}/credits", json={"delta": 100, "reason": "myself"}).status_code == 403
    boss, _ = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    assert boss.post(f"/api/admin/users/{other_admin}/suspend", json={"reason": "offboarding"}).status_code == 204


def test_only_a_superadmin_with_a_fresh_sign_in_deletes_users(admin, new_browser, pg_engine):
    browser, _ = admin
    uid = make_user(pg_engine, "ada@example.com")
    assert browser.request("DELETE", f"/api/admin/users/{uid}", json={"reason": "gdpr request"}).status_code == 403
    boss, boss_id = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    assert boss.request("DELETE", f"/api/admin/users/{uid}", json={"reason": "erasure request #12"}).status_code == 204
    assert scalar(pg_engine, "SELECT deleted_at IS NOT NULL FROM users WHERE id = :u", u=uid)
    assert scalar(pg_engine, "SELECT count(*) FROM accounts WHERE user_id = :u", u=uid) == 0
    [row] = audit_rows(pg_engine, uid)
    assert (row["action"], row["actor_id"], row["reason"]) == ("users.delete", boss_id, "erasure request #12")


# --- invite codes ---------------------------------------------------------------------------------


def test_bulk_codes_are_unique_unguessable_and_shown_once(admin, pg_engine):
    browser, _ = admin
    res = browser.post("/api/admin/invites", json={"count": 500, "campaign": "launch", "max_uses": 2})
    assert res.status_code == 201
    codes = res.json()["codes"]
    assert len(codes) == len(set(codes)) == 500
    assert all(len(normalize(c)) == 12 and set(normalize(c)) <= set(ALPHABET) for c in codes)
    assert scalar(pg_engine, "SELECT count(DISTINCT code_hash) FROM invites WHERE campaign = 'launch'") == 500
    assert scalar(pg_engine, "SELECT count(*) FROM invites WHERE code_hash = :h", h=hash_code(codes[0])) == 1
    listed = browser.get("/api/admin/invites", params={"campaign": "launch", "page_size": 5}).json()
    assert listed["total"] == 500 and all(len(i["code_hint"]) == 4 for i in listed["items"])
    assert codes[0] not in json.dumps(listed)
    batch = res.json()["batch_id"]
    [row] = audit_rows(pg_engine, batch)
    assert row["action"] == "invites.generate" and row["after"]["count"] == 500
    with pg_engine.connect() as conn:
        logged = json.dumps([list(r) for r in conn.execute(text("SELECT before, after FROM admin_audit_log")).all()])
    assert not any(c in logged for c in codes)


def test_generate_validates(admin):
    browser, _ = admin
    assert browser.post("/api/admin/invites", json={"count": 501}).status_code == 422
    assert browser.post("/api/admin/invites", json={"count": 2, "email": "a@example.com"}).json()["detail"] == \
        "email_lock_needs_one_code"
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert browser.post("/api/admin/invites", json={"expires_at": past}).json()["detail"] == "expiry_in_past"


def pending_signup(new_browser, email, account):
    b = new_browser()
    assert post(b, "/test/identity", {"provider": "github", "provider_account_id": account,
                                      "verified_email": email}).json()["next"] == "invite"
    return b


def check(b, code):
    return post(b, "/api/auth/signup/invite", {"code": code})


def test_redemption_refuses_expired_revoked_exhausted_and_locked_codes(admin, new_browser, notices, pg_engine):
    browser, _ = admin
    make = lambda **kw: browser.post("/api/admin/invites", json=kw).json()["codes"][0]  # noqa: E731
    locked, expiring, revoked, single = make(email="other@example.org"), make(), make(), make()
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE invites SET expires_at = now() - interval '1 minute' WHERE code_hash = :h"),
                     {"h": hash_code(expiring)})
    rid = scalar(pg_engine, "SELECT id FROM invites WHERE code_hash = :h", h=hash_code(revoked))
    assert browser.post(f"/api/admin/invites/{rid}/revoke", json={"reason": "leaked on twitter"}).status_code == 204

    b = pending_signup(new_browser, "friend@example.org", "f-1")
    for code in (locked, expiring, revoked):
        assert check(b, code).json()["detail"] == "no_invite", code
    assert check(b, single).json() == {"next": "consent"}
    assert post(b, "/api/auth/signup/complete", consent(notices)).json() == {"next": "signed_in"}
    c = pending_signup(new_browser, "second@example.org", "f-2")
    assert check(c, single).json()["detail"] == "no_invite"  # exhausted
    statuses = {i["code_hint"]: i["status"] for i in browser.get("/api/admin/invites").json()["items"]}
    assert (statuses[expiring[-4:]], statuses[revoked[-4:]], statuses[single[-4:]]) == ("expired", "revoked", "exhausted")


def test_redemption_is_atomic(admin, new_browser, notices, pg_engine):
    """Two people pass the code check with the same single-use code and finish sign-up
    at the same moment: exactly one account is made."""
    browser, _ = admin
    code = browser.post("/api/admin/invites", json={}).json()["codes"][0]
    first, second = pending_signup(new_browser, "a@example.org", "a-1"), pending_signup(new_browser, "b@example.org", "b-1")
    assert check(first, code).json() == check(second, code).json() == {"next": "consent"}
    start, results = threading.Barrier(2), []

    def finish(b):
        token = csrf(b)
        start.wait()
        results.append(b.post("/api/auth/signup/complete", json=consent(notices), headers=token).json())

    threads = [threading.Thread(target=finish, args=(b,)) for b in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(json.dumps(r) for r in results) == sorted([json.dumps({"next": "signed_in"}),
                                                             json.dumps({"detail": "invite_unavailable"})])
    assert scalar(pg_engine, "SELECT uses FROM invites") == 1
    assert scalar(pg_engine, "SELECT count(*) FROM users WHERE email IN ('a@example.org', 'b@example.org')") == 1


def test_bonus_and_starter_credits_land_in_the_ledger(admin, new_browser, notices, pg_engine):
    browser, _ = admin
    boss, _ = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    assert boss.put("/api/admin/settings/signup_bonus_credits", json={"value": 2, "reason": "launch week"}).status_code == 200
    code = browser.post("/api/admin/invites", json={"bonus_credits": 3}).json()["codes"][0]
    b = pending_signup(new_browser, "friend@example.org", "f-1")
    check(b, code)
    post(b, "/api/auth/signup/complete", consent(notices))
    uid = scalar(pg_engine, "SELECT id FROM users WHERE email = 'friend@example.org'")
    assert [(r["delta"], r["reason"], r["note"]) for r in ledger(pg_engine, uid)] == [
        (2, "signup_bonus", "starter credits"), (3, "signup_bonus", "invite code bonus")]


def test_extend_and_funnel(admin, new_browser, notices, pg_engine):
    browser, _ = admin
    code = browser.post("/api/admin/invites", json={}).json()["codes"][0]
    iid = scalar(pg_engine, "SELECT id FROM invites")
    later = (datetime.now(UTC) + timedelta(days=60)).isoformat()
    assert browser.post(f"/api/admin/invites/{iid}/extend", json={"expires_at": later, "reason": "event moved"}).status_code == 204
    b = pending_signup(new_browser, "friend@example.org", "f-1")
    check(b, code)
    post(b, "/api/auth/signup/complete", consent(notices))
    b.headers.update(csrf(b))
    resume = b.post("/api/resume/parse", files={"file": ("r.txt", fixture_text("resume_analyst.txt"))}).json()
    jd = b.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")}).json()
    aid = b.post("/api/analyses", json={"resume": resume, "jd": jd}).json()["analysis_id"]
    b.post("/api/tailor", json={"resume": resume, "jd": jd, "use_llm": False}, headers={"X-Analysis-Id": aid})
    [admin_row] = [r for r in browser.get("/api/admin/invites/funnel").json() if r["kind"] == "admin"]
    assert admin_row == {"kind": "admin", "created": 1, "redeemed": 1, "first_tailoring": 1}
    assert [r["action"] for r in audit_rows(pg_engine, iid)] == ["invites.extend"]


def test_admin_revoking_a_personal_invite_returns_the_slot(admin, new_browser, pg_engine):
    browser, _ = admin
    friend_inviter, inviter_id = signed_in(new_browser, pg_engine, "user", "inviter@example.com")
    iid = friend_inviter.post("/api/invites", json={"email": "pal@example.org"}).json()["id"]
    assert scalar(pg_engine, "SELECT invites_created FROM users WHERE id = :u", u=inviter_id) == 1
    assert browser.post(f"/api/admin/invites/{iid}/revoke", json={"reason": "spam report"}).status_code == 204
    assert scalar(pg_engine, "SELECT invites_created FROM users WHERE id = :u", u=inviter_id) == 0


# --- waitlist ------------------------------------------------------------------------------------


def add_waitlist(pg_engine, notices, email):
    with pg_engine.begin() as conn:
        return conn.execute(text("INSERT INTO waitlist (email, notice_id) VALUES (:e, :n) RETURNING id"),
                            {"e": email, "n": notices["waitlist"]}).scalar_one()


def test_approving_the_waitlist_invites_by_email(admin, new_browser, notices, outbox, pg_engine):
    browser, _ = admin
    a, b = add_waitlist(pg_engine, notices, "a@example.org"), add_waitlist(pg_engine, notices, "b@example.org")
    res = browser.post("/api/admin/waitlist/approve", json={"ids": [str(a), str(a), str(b)], "reason": "batch 1"}).json()
    assert res == {"approved": 2, "skipped": 0, "failed": 0}
    assert sorted(m.to for m in outbox) == ["a@example.org", "b@example.org"]
    assert browser.get("/api/admin/waitlist").json()["items"] == []  # nobody waiting now
    assert scalar(pg_engine, "SELECT count(*) FROM invites WHERE kind = 'waitlist' AND email = 'a@example.org'") == 1
    again = browser.post("/api/admin/waitlist/approve", json={"ids": [str(a)]}).json()
    assert again == {"approved": 0, "skipped": 1, "failed": 0}
    # The invited address signs up with no code to type.
    s = pending_signup(new_browser, "a@example.org", "a-1")
    assert post(s, "/api/auth/signup/invite", {}).json() == {"next": "consent"}


def test_a_failed_waitlist_email_leaves_the_entry_waiting(admin, notices, pg_engine, monkeypatch):
    from app.api import admin_invites
    from app.auth.mailer import MailerError

    class Broken:
        def send(self, mail):
            raise MailerError("network")

    monkeypatch.setattr(admin_invites, "get_mailer", lambda: Broken())
    browser, _ = admin
    a = add_waitlist(pg_engine, notices, "a@example.org")
    assert browser.post("/api/admin/waitlist/approve", json={"ids": [str(a)]}).json()["failed"] == 1
    assert scalar(pg_engine, "SELECT status FROM waitlist WHERE id = :i", i=a) == "waiting"
    assert scalar(pg_engine, "SELECT count(*) FROM invites") == 0


def test_reject_and_delete_waitlist_entries(admin, notices, pg_engine):
    browser, _ = admin
    a, b = add_waitlist(pg_engine, notices, "a@example.org"), add_waitlist(pg_engine, notices, "b@example.org")
    assert browser.post("/api/admin/waitlist/reject", json={"ids": [str(a)], "reason": "spam"}).json() == {"rejected": 1}
    assert browser.get("/api/admin/waitlist", params={"status": "rejected"}).json()["items"][0]["email"] == "a@example.org"
    assert browser.request("DELETE", f"/api/admin/waitlist/{b}", json={"reason": "asked to be removed"}).status_code == 204
    assert scalar(pg_engine, "SELECT count(*) FROM waitlist WHERE id = :i", i=b) == 0
    assert [r["action"] for r in audit_rows(pg_engine, b)] == ["waitlist.delete"]


# --- support inbox -------------------------------------------------------------------------------


def ticket(new_browser, pg_engine, email="ada@example.com"):
    user, uid = signed_in(new_browser, pg_engine, "user", email)
    tid = user.post("/api/support/tickets", json={"category": "billing", "subject": "Double charge",
                                                  "body": "I was charged twice."}).json()["id"]
    return user, uid, tid


def test_support_replies_by_email_notes_stay_internal(support, new_browser, outbox, pg_engine):
    staff, staff_id = support
    user, _, tid = ticket(new_browser, pg_engine)
    [row] = staff.get("/api/admin/support").json()["items"]
    assert (row["subject"], row["status"], row["assignee_id"]) == ("Double charge", "open", None)
    detail = staff.get(f"/api/admin/support/{tid}").json()
    assert detail["body"] == "I was charged twice." and detail["messages"] == []

    assert staff.post(f"/api/admin/support/{tid}/note", json={"body": "Check Dodo for pay_123."}).status_code == 201
    assert outbox == []  # notes are never emailed
    assert staff.post(f"/api/admin/support/{tid}/reply", json={"body": "Refunded the second charge."}).status_code == 201
    [mail] = outbox
    assert mail.to == "ada@example.com" and mail.subject == "Re: Double charge"
    assert "Refunded the second charge." in mail.lines and "pay_123" not in json.dumps(mail.lines)
    detail = staff.get(f"/api/admin/support/{tid}").json()
    assert [m["kind"] for m in detail["messages"]] == ["internal_note", "reply"]
    assert (detail["status"], detail["assignee_id"]) == ("pending", str(staff_id))
    assert user.get("/api/support/tickets").json()[0]["status"] == "pending"
    assert "pay_123" not in user.get("/api/support/tickets").text
    rows = audit_rows(pg_engine, tid)
    assert [r["action"] for r in rows] == ["tickets.note", "tickets.reply"]
    assert all("pay_123" not in json.dumps(r, default=str) and "Refunded" not in json.dumps(r, default=str) for r in rows)


def test_assign_close_and_filter(support, admin, new_browser, pg_engine):
    staff, staff_id = support
    _, admin_id = admin
    _, _, tid = ticket(new_browser, pg_engine)
    customer = make_user(pg_engine, "customer@example.com")
    assert staff.patch(f"/api/admin/support/{tid}", json={"assignee_id": str(customer)}).json()["detail"] == "not_staff"
    out = staff.patch(f"/api/admin/support/{tid}", json={"assignee_id": str(admin_id), "status": "closed"}).json()
    assert (out["status"], out["assignee_id"]) == ("closed", str(admin_id))
    assert staff.get("/api/admin/support").json()["items"] == []  # active only by default
    assert staff.get("/api/admin/support", params={"status": "closed"}).json()["total"] == 1
    assert [r["action"] for r in audit_rows(pg_engine, tid)] == ["tickets.update"]


def test_a_normal_user_cannot_read_the_inbox(new_browser, pg_engine):
    user, _, tid = ticket(new_browser, pg_engine)
    assert user.get("/api/admin/support").status_code == 403
    assert user.get(f"/api/admin/support/{tid}").status_code == 403


# --- runtime settings for invites and referrals ---------------------------------------------------


def test_runtime_settings_change_the_quota_and_the_reward(new_browser, pg_engine):
    boss, _ = signed_in(new_browser, pg_engine, "superadmin", "boss@example.com")
    user, uid = signed_in(new_browser, pg_engine, "user", "ada@example.com")
    assert user.get("/api/invites").json()["limit"] == 10
    assert boss.put("/api/admin/settings/invites_per_user", json={"value": 3, "reason": "slow rollout"}).status_code == 200
    assert user.get("/api/invites").json()["limit"] == 3
    assert boss.put("/api/admin/settings/invites_per_user", json={"value": 500, "reason": "x" * 3}).status_code == 422
    assert boss.put("/api/admin/settings/referral_reward_credits", json={"value": 2, "reason": "promo"}).status_code == 200
    assert user.get("/api/invites").json()["reward_credits"] == 2
    assert boss.put("/api/admin/settings/invite_only", json={"value": False, "reason": "open beta"}).status_code == 200
    assert new_browser().get("/api/auth/config").json() == {"invite_only": False}
