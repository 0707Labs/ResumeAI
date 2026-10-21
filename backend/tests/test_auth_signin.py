"""Magic link, the invite gate and the account-creating transaction.

/test/identity stands in for an OAuth callback (Google/GitHub arrive next step):
it runs the same resolve -> sign in / pending logic."""

import asyncio
import json
import logging
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.invites import hash_code
from app.auth.signup import SignupError, complete_signup
from app.db.models import PendingAuth

NEW = "new.person@example.com"


# --- helpers ---------------------------------------------------------------------------


def csrf(client) -> dict[str, str]:
    return {"X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]}


def post(client, path, body=None):
    return client.post(path, json=body, headers=csrf(client))


def count(pg_engine, table: str, where: str = "true") -> int:
    with pg_engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table} WHERE {where}")).scalar_one()


def scalar(pg_engine, sql: str, **params):
    with pg_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def magic_link(client, outbox, email=NEW):
    """Request a sign-in link and open it in the same browser."""
    assert post(client, "/api/auth/email/start", {"email": email}).status_code == 202
    return post(client, "/api/auth/email/verify", {"token": outbox.last_token()})


def consent(notices, research=False) -> dict:
    ids = {"service": notices["service"], "age_18_plus": notices["age_18_plus"]}
    if research:
        ids["research"] = notices["research"]
    return {"age_18_plus": True, "accept_terms": True, "research_opt_in": research, "notice_ids": ids}


def sign_up(client, outbox, notices, code, email=NEW):
    assert magic_link(client, outbox, email).json() == {"next": "invite"}
    assert post(client, "/api/auth/signup/invite", {"code": code}).json() == {"next": "consent"}
    return post(client, "/api/auth/signup/complete", consent(notices))


# --- existing users ------------------------------------------------------------------------


def test_existing_user_signs_in_by_magic_link_and_gets_an_email_login(client, outbox, user_id, pg_engine):
    res = magic_link(client, outbox, "Ada@Example.com ")
    assert res.json() == {"next": "signed_in"}
    assert client.get("/api/me").json()["id"] == str(user_id)
    assert count(pg_engine, "accounts", "provider = 'email' AND provider_account_id = 'ada@example.com'") == 1
    assert count(pg_engine, "pending_auth") == 0


def test_suspended_user_cannot_sign_in(client, outbox, user_id, pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET status = 'suspended'"))
    res = magic_link(client, outbox, "ada@example.com")
    assert res.status_code == 403 and res.json()["detail"] == "account_unavailable"
    assert client.get("/api/me").status_code == 401


def test_same_verified_email_via_another_provider_links_to_the_same_user(client, user_id, pg_engine):
    res = post(client, "/test/identity",
               {"provider": "github", "provider_account_id": "4242", "verified_email": "ada@example.com"})
    assert res.json() == {"next": "signed_in"}
    assert count(pg_engine, "users") == 1
    assert scalar(pg_engine, "SELECT user_id FROM accounts WHERE provider = 'github'") == user_id


# --- magic link mechanics --------------------------------------------------------------------


def test_magic_link_answer_does_not_reveal_whether_the_email_is_known(client, outbox, user_id):
    known = post(client, "/api/auth/email/start", {"email": "ada@example.com"})
    unknown = post(client, "/api/auth/email/start", {"email": NEW})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(outbox) == 2 and outbox[0].link.startswith("http://localhost:3000/auth/email#token=")


def test_magic_link_is_single_use(client, outbox, user_id):
    assert magic_link(client, outbox, "ada@example.com").json() == {"next": "signed_in"}
    again = post(client, "/api/auth/email/verify", {"token": outbox.last_token()})
    assert again.status_code == 400 and again.json()["detail"] == "link_invalid"


def test_expired_magic_link_is_rejected(client, outbox, pg_engine):
    post(client, "/api/auth/email/start", {"email": NEW})
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE email_tokens SET expires_at = now() - interval '1 second'"))
    res = post(client, "/api/auth/email/verify", {"token": outbox.last_token()})
    assert res.json()["detail"] == "link_invalid"


def test_magic_link_requests_are_limited_per_address(client):
    codes = [post(client, "/api/auth/email/start", {"email": NEW}).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]


def test_magic_link_start_requires_csrf(client, outbox):
    assert client.post("/api/auth/email/start", json={"email": NEW}).status_code == 403
    assert outbox == []


# --- invite gate --------------------------------------------------------------------------------


def test_new_user_without_invite_gets_no_account(client, outbox, notices, pg_engine):
    assert magic_link(client, outbox).json() == {"next": "invite"}
    assert client.get("/api/me").status_code == 401
    assert count(pg_engine, "users") == 0

    pending = client.get("/api/auth/pending").json()
    assert pending == {"kind": "signup", "provider": "email", "email": NEW, "invite_required": True,
                       "invite_accepted": False, "has_bound_invite": False}

    bad = post(client, "/api/auth/signup/invite", {"code": "NOPE-NOPE-NOPE"})
    assert bad.status_code == 400 and bad.json()["detail"] == "no_invite"
    assert post(client, "/api/auth/signup/invite", {}).json()["detail"] == "no_invite"
    skipped = post(client, "/api/auth/signup/complete", consent(notices))
    assert skipped.status_code == 400 and skipped.json()["detail"] == "invite_required"
    assert count(pg_engine, "users") == 0 and count(pg_engine, "accounts") == 0


def test_invite_only_is_on_unless_switched_off(client, monkeypatch):
    assert client.get("/api/auth/config").json() == {"invite_only": True}
    monkeypatch.setenv("RT_INVITE_ONLY", "0")
    assert client.get("/api/auth/config").json() == {"invite_only": False}


def test_open_signup_skips_the_invite_step(client, outbox, notices, monkeypatch, pg_engine):
    monkeypatch.setenv("RT_INVITE_ONLY", "off")
    assert magic_link(client, outbox).json() == {"next": "consent"}
    assert client.get("/api/auth/pending").json()["invite_required"] is False
    assert post(client, "/api/auth/signup/complete", consent(notices)).json() == {"next": "signed_in"}
    assert client.get("/api/me").json()["email"] == NEW
    assert count(pg_engine, "users") == 1 and count(pg_engine, "invite_redemptions") == 0


def test_open_signup_still_uses_up_an_invite_that_was_entered(client, outbox, notices, make_invite, monkeypatch,
                                                              pg_engine):
    monkeypatch.setenv("RT_INVITE_ONLY", "0")
    code = make_invite()
    magic_link(client, outbox)
    assert post(client, "/api/auth/signup/invite", {"code": code}).json() == {"next": "consent"}
    assert post(client, "/api/auth/signup/complete", consent(notices)).json() == {"next": "signed_in"}
    assert count(pg_engine, "invite_redemptions") == 1 and scalar(pg_engine, "SELECT uses FROM invites") == 1


def test_open_signup_via_unverified_identity_goes_to_consent_after_verifying(client, outbox, monkeypatch):
    monkeypatch.setenv("RT_INVITE_ONLY", "0")
    assert github_without_email(client).json() == {"next": "verify_email"}
    assert post(client, "/api/auth/pending/email", {"email": NEW}).status_code == 202
    assert post(client, "/api/auth/email/verify", {"token": outbox.last_token()}).json() == {"next": "consent"}


def test_no_invite_can_join_the_waitlist_with_the_pending_email(client, outbox, notices, pg_engine):
    magic_link(client, outbox)
    email = client.get("/api/auth/pending").json()["email"]
    body = {"email": email, "age_18_plus": True, "notice_id": notices["waitlist"]}
    first, second = post(client, "/api/waitlist", body), post(client, "/api/waitlist", body)
    assert first.status_code == second.status_code == 202 and first.json() == second.json()
    assert count(pg_engine, "waitlist") == 1
    assert post(client, "/api/waitlist", body | {"age_18_plus": False}).status_code == 422


def test_new_user_with_invite_is_created_once(client, outbox, notices, make_invite, pg_engine):
    code = make_invite()
    res = sign_up(client, outbox, notices, code)
    assert res.json() == {"next": "signed_in"}
    me = client.get("/api/me").json()
    assert me["email"] == NEW and me["status"] == "active"

    assert count(pg_engine, "users") == 1
    assert count(pg_engine, "accounts", f"provider = 'email' AND provider_account_id = '{NEW}'") == 1
    assert count(pg_engine, "invite_redemptions") == 1
    assert scalar(pg_engine, "SELECT uses FROM invites") == 1
    assert count(pg_engine, "pending_auth") == 0
    assert sorted(scalar(pg_engine, "SELECT array_agg(purpose) FROM consent_records")) == ["age_18_plus", "service"]
    assert scalar(pg_engine, "SELECT terms_version FROM users") == "2026-11-v1"

    # Double submit after success: the pending identity is gone.
    again = post(client, "/api/auth/signup/complete", consent(notices))
    assert again.json()["detail"] == "pending_expired"
    assert count(pg_engine, "users") == 1


def test_used_invite_cannot_be_reused(new_browser, outbox, notices, make_invite, pg_engine):
    code = make_invite()
    assert sign_up(new_browser(), outbox, notices, code).json() == {"next": "signed_in"}
    other = new_browser()
    assert magic_link(other, outbox, "someone.else@example.com").json() == {"next": "invite"}
    res = post(other, "/api/auth/signup/invite", {"code": code})
    assert res.status_code == 400 and res.json()["detail"] == "no_invite"
    assert count(pg_engine, "users") == 1


def test_invite_is_consumed_only_at_account_creation(new_browser, outbox, notices, make_invite, pg_engine):
    """Two people pass the invite step with a single-use code; only the first to finish gets in."""
    code = make_invite()
    a, b = new_browser(), new_browser()
    for browser, email in ((a, "a@example.com"), (b, "b@example.com")):
        magic_link(browser, outbox, email)
        assert post(browser, "/api/auth/signup/invite", {"code": code}).json() == {"next": "consent"}
    assert scalar(pg_engine, "SELECT uses FROM invites") == 0  # checking doesn't burn it

    assert post(a, "/api/auth/signup/complete", consent(notices)).json() == {"next": "signed_in"}
    late = post(b, "/api/auth/signup/complete", consent(notices))
    assert late.status_code == 409 and late.json()["detail"] == "invite_unavailable"
    assert b.get("/api/auth/pending").json()["invite_accepted"] is False  # back to the invite step
    assert count(pg_engine, "users") == 1 and scalar(pg_engine, "SELECT uses FROM invites") == 1


def test_concurrent_completions_on_one_invite_create_exactly_one_user(pg_url, pg_engine, api_app, make_invite,
                                                                     notices):
    code = make_invite()
    invite_id = scalar(pg_engine, "SELECT id FROM invites WHERE code_hash = :h", h=hash_code(code))
    with pg_engine.begin() as conn:
        pending_ids = [conn.execute(text(
            "INSERT INTO pending_auth (token_hash, kind, provider, provider_account_id, verified_email,"
            " invite_id, expires_at) VALUES (:t, 'signup', 'email', :e, :e, :i, now() + interval '15 minutes')"
            " RETURNING id"
        ), {"t": uuid.uuid4().hex, "e": f"p{i}@example.com", "i": invite_id}).scalar_one() for i in range(20)]
    ids = {k: uuid.UUID(v) for k, v in notices.items() if k in ("service", "age_18_plus")}

    async def attempt(sessions, pending_id):
        async with sessions() as db:
            pending = await db.get(PendingAuth, pending_id, with_for_update=True)
            try:
                await complete_signup(db, pending, notice_ids=ids, research_opt_in=False, ip=None)
                return "ok"
            except SignupError as exc:
                return exc.code

    async def race():
        engine = create_async_engine(pg_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            return await asyncio.gather(*(attempt(sessions, p) for p in pending_ids))
        finally:
            await engine.dispose()

    results = asyncio.run(race())
    assert results.count("ok") == 1 and results.count("invite_unavailable") == 19
    assert count(pg_engine, "users") == 1
    assert scalar(pg_engine, "SELECT uses FROM invites") == 1


def test_invite_bound_to_the_email_needs_no_code(client, outbox, notices, make_invite):
    make_invite(email=NEW)
    magic_link(client, outbox)
    assert client.get("/api/auth/pending").json()["has_bound_invite"] is True
    assert post(client, "/api/auth/signup/invite", {}).json() == {"next": "consent"}
    assert post(client, "/api/auth/signup/complete", consent(notices)).json() == {"next": "signed_in"}


def test_invite_bound_to_another_email_is_refused(client, outbox, make_invite):
    code = make_invite(email="someone.else@example.com")
    magic_link(client, outbox)
    assert post(client, "/api/auth/signup/invite", {"code": code}).json()["detail"] == "no_invite"


@pytest.mark.parametrize("extra", ["revoked_at=now()", "expires_at=now() - interval '1 day'"])
def test_revoked_or_expired_invite_is_refused(client, outbox, make_invite, extra):
    code = make_invite(extra=extra)
    magic_link(client, outbox)
    assert post(client, "/api/auth/signup/invite", {"code": code}).json()["detail"] == "no_invite"


def test_invite_codes_are_forgiving_about_case_and_dashes(client, outbox, make_invite):
    code = make_invite()
    magic_link(client, outbox)
    sloppy = code.lower().replace("-", " ")
    assert post(client, "/api/auth/signup/invite", {"code": sloppy}).json() == {"next": "consent"}


# --- consent ----------------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["age_18_plus", "accept_terms"])
def test_required_consent_is_required(client, outbox, notices, make_invite, pg_engine, missing):
    magic_link(client, outbox)
    post(client, "/api/auth/signup/invite", {"code": make_invite()})
    for value in (False, None):
        body = consent(notices) | {missing: value}
        assert post(client, "/api/auth/signup/complete", body).status_code == 422
    assert count(pg_engine, "users") == 0 and scalar(pg_engine, "SELECT uses FROM invites") == 0


def test_research_consent_is_optional_and_recorded_only_when_ticked(new_browser, outbox, notices, make_invite,
                                                                   pg_engine):
    a = new_browser()
    sign_up(a, outbox, notices, make_invite(), "a@example.com")
    b = new_browser()
    magic_link(b, outbox, "b@example.com")
    post(b, "/api/auth/signup/invite", {"code": make_invite()})
    assert post(b, "/api/auth/signup/complete", consent(notices, research=True)).json() == {"next": "signed_in"}
    assert count(pg_engine, "consent_records", "purpose = 'research'") == 1
    assert scalar(pg_engine, "SELECT u.email FROM consent_records c JOIN users u ON u.id = c.user_id"
                             " WHERE c.purpose = 'research'") == "b@example.com"


def test_consent_to_an_outdated_notice_is_refused(client, outbox, notices, make_invite, pg_engine):
    magic_link(client, outbox)
    post(client, "/api/auth/signup/invite", {"code": make_invite()})
    with pg_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO consent_notices (purpose, version, body_sha256, body_url, published_at)"
            " VALUES ('service', '2026-12-v2', :h, '/legal/service', now())"
        ), {"h": "1" * 64})
    res = post(client, "/api/auth/signup/complete", consent(notices))
    assert res.status_code == 400 and res.json()["detail"] == "stale_notice"
    assert count(pg_engine, "users") == 0 and scalar(pg_engine, "SELECT uses FROM invites") == 0


def test_notices_lists_the_current_versions(client, notices):
    listed = {n["purpose"]: n["id"] for n in client.get("/api/auth/notices").json()}
    assert listed == notices


# --- provider without a verified email (GitHub) ------------------------------------------------


def github_without_email(client):
    return post(client, "/test/identity", {"provider": "github", "provider_account_id": "777"})


def test_no_verified_email_must_verify_one_before_the_invite_step(client, outbox, notices, make_invite,
                                                                pg_engine):
    assert github_without_email(client).json() == {"next": "verify_email"}
    assert client.get("/api/auth/pending").json()["email"] is None
    code = make_invite()
    blocked = post(client, "/api/auth/signup/invite", {"code": code})
    assert blocked.status_code == 400 and blocked.json()["detail"] == "email_unverified"
    assert post(client, "/api/auth/signup/complete", consent(notices)).json()["detail"] == "email_unverified"

    assert post(client, "/api/auth/pending/email", {"email": NEW}).status_code == 202
    assert outbox[-1].to == NEW
    assert post(client, "/api/auth/email/verify", {"token": outbox.last_token()}).json() == {"next": "invite"}
    assert client.get("/api/auth/pending").json()["email"] == NEW

    post(client, "/api/auth/signup/invite", {"code": code})
    assert post(client, "/api/auth/signup/complete", consent(notices)).json() == {"next": "signed_in"}
    assert scalar(pg_engine, "SELECT email_at_link FROM accounts WHERE provider = 'github'"
                             " AND provider_account_id = '777'") == NEW


def test_verifying_an_email_of_an_existing_user_links_and_signs_in(client, outbox, user_id, pg_engine):
    github_without_email(client)
    post(client, "/api/auth/pending/email", {"email": "ada@example.com"})
    res = post(client, "/api/auth/email/verify", {"token": outbox.last_token()})
    assert res.json() == {"next": "signed_in"}
    assert scalar(pg_engine, "SELECT user_id FROM accounts WHERE provider = 'github'") == user_id
    assert count(pg_engine, "pending_auth") == 0


def test_unverified_identity_never_links_to_an_existing_user(client, user_id, pg_engine):
    assert github_without_email(client).json() == {"next": "verify_email"}
    assert count(pg_engine, "accounts") == 0
    assert client.get("/api/me").status_code == 401


def test_email_verification_link_only_works_in_the_same_browser(new_browser, outbox, pg_engine):
    started, other = new_browser(), new_browser()
    github_without_email(started)
    post(started, "/api/auth/pending/email", {"email": NEW})
    token = outbox.last_token()
    wrong = post(other, "/api/auth/email/verify", {"token": token})
    assert wrong.status_code == 400 and wrong.json()["detail"] == "wrong_browser"
    assert post(started, "/api/auth/email/verify", {"token": token}).json() == {"next": "invite"}


def test_expired_pending_identity_cannot_continue(client, outbox, make_invite, pg_engine):
    magic_link(client, outbox)
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE pending_auth SET expires_at = now() - interval '1 second'"))
    assert client.get("/api/auth/pending").status_code == 404
    res = post(client, "/api/auth/signup/invite", {"code": make_invite()})
    assert res.json()["detail"] == "pending_expired"


def test_tampered_pending_cookie_is_ignored(client, outbox):
    magic_link(client, outbox)
    value = client.cookies["rt_pending"]
    client.cookies.set("rt_pending", value[:-1] + ("0" if value[-1] != "0" else "1"))
    assert client.get("/api/auth/pending").status_code == 404


# --- logs ---------------------------------------------------------------------------------------


def test_sign_up_logs_carry_no_email_or_code(client, outbox, notices, make_invite, caplog):
    caplog.set_level(logging.INFO, logger="app.auth.events")
    code = make_invite()
    sign_up(client, outbox, notices, code)
    lines = [r.getMessage() for r in caplog.records if r.name == "app.auth.events"]
    assert [json.loads(line)["event"] for line in lines] == [
        "magic_link_sent", "magic_link_used", "pending_created", "invite_checked",
        "signup_completed", "login",
    ]
    blob = "\n".join(lines)
    for secret in (NEW, code, outbox.last_token(), "new.person"):
        assert secret not in blob
