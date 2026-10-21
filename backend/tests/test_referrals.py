"""Referrals: codes and links, attribution at sign-up, the two triggers, rewards through
the ledger once and within the monthly cap, abuse controls (self and alias, disposable
email, duplicate referee, same-network review), the admin queue, invite-only referral
invites with their limit, and the header's live updates."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import signup as signup_module
from app.billing import referrals
from app.billing.config import get_billing_config
from app.db.models import User
from tests.test_analyses import fixture_text
from tests.test_auth_signin import consent, csrf, post


def sql(pg_engine, stmt, **params):
    with pg_engine.begin() as conn:
        res = conn.execute(text(stmt), params)
        return res.scalar() if res.returns_rows else None


def cfg(monkeypatch, **referral_settings):
    """Override [referrals] for this test (sign-up reads the config directly)."""
    base = get_billing_config()
    config = base.model_copy(update={"referrals": base.referrals.model_copy(update=referral_settings)})
    monkeypatch.setattr(signup_module, "get_billing_config", lambda: config)
    return config


@pytest.fixture
def config_override(api_app):
    """Route-level override of the billing config."""
    def apply(config):
        api_app.dependency_overrides[get_billing_config] = lambda: config
    return apply


def new_user(pg_engine, email):
    return sql(pg_engine, "INSERT INTO users (email, email_verified_at, activated_at, age_confirmed_at,"
                          " terms_version, terms_accepted_at) VALUES (:e, now(), now(), now(), 'v1', now())"
                          " RETURNING id", e=email)


def signed_in_as(new_browser, uid):
    b = new_browser()
    assert b.post(f"/test/login/{uid}").status_code == 200
    b.headers.update(csrf(b))
    return b


@pytest.fixture
def referrer(new_browser, pg_engine):
    uid = new_user(pg_engine, "ada@gmail.com")
    browser = signed_in_as(new_browser, uid)
    code = browser.get("/api/referrals").json()["code"]
    return uid, browser, code


def balance(pg_engine, uid):
    return sql(pg_engine, "SELECT credits_balance FROM users WHERE id = :u", u=uid)


def referral(pg_engine, column, referee_email):
    return sql(pg_engine, f"SELECT r.{column} FROM referrals r JOIN users u ON u.id = r.referee_id"
                          " WHERE u.email = :e", e=referee_email)


def join(new_browser, notices, code, email, *, invite=None, referral_invite=False, account=None):
    """A friend signs up (an OAuth-style verified identity) with the rt_ref cookie set."""
    friend = new_browser()
    if code:
        friend.cookies.set(referrals.COOKIE, code)
    step = post(friend, "/test/identity", {"provider": "github", "provider_account_id": account or email,
                                           "verified_email": email}).json()["next"]
    if step == "invite":
        body = {"referral": True} if referral_invite else {"code": invite}
        res = post(friend, "/api/auth/signup/invite", body)
        if res.status_code != 200:
            return friend, res
    res = post(friend, "/api/auth/signup/complete", consent(notices))
    friend.headers.update(csrf(friend))
    return friend, res


def tailor(friend):
    resume = friend.post("/api/resume/parse", files={"file": ("r.txt", fixture_text("resume_analyst.txt"))}).json()
    jd = friend.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")}).json()
    aid = friend.post("/api/analyses", json={"resume": resume, "jd": jd}).json()["analysis_id"]
    res = friend.post("/api/tailor", json={"resume": resume, "jd": jd, "use_llm": False}, headers={"X-Analysis-Id": aid})
    assert res.status_code == 200


@pytest.fixture(autouse=True)
def open_signup(monkeypatch):
    monkeypatch.setenv("RT_INVITE_ONLY", "0")


# --- pure helpers -----------------------------------------------------------------------------


def test_aliases_of_one_address_are_one_person():
    key = referrals.same_person_key
    assert key("Ada.Lovelace+jobs@Gmail.com") == key("adalovelace@googlemail.com") == "adalovelace@gmail.com"
    assert key("ada+x@example.com") == key("ada@example.com") != key("a.da@example.com")


def test_disposable_domains_and_codes():
    config = get_billing_config()
    assert referrals.is_disposable("x@mailinator.com", config) and referrals.is_disposable("x@eu.yopmail.com", config)
    assert not referrals.is_disposable("x@example.com", config)
    assert referrals.normalize_code(" abcd-efgh ") == "ABCDEFGH" and referrals.normalize_code("../etc") is None


# --- links and attribution --------------------------------------------------------------------------


def test_each_user_has_one_stable_code_and_link(referrer):
    uid, browser, code = referrer
    again = browser.get("/api/referrals").json()
    assert again["code"] == code and again["link"].endswith(f"/?ref={code}")
    assert (again["trigger"], again["reward_credits"], again["monthly_cap"]) == ("on_first_tailoring", 1, 10)
    assert again["referrals"] == [] and again["total_earned"] == 0


def test_reward_on_first_tailoring_once(referrer, new_browser, notices, pg_engine):
    uid, browser, code = referrer
    friend, res = join(new_browser, notices, code, "friend@example.com")
    assert res.json() == {"next": "signed_in"}
    assert referral(pg_engine, "status", "friend@example.com") == "pending"
    assert balance(pg_engine, uid) == 0

    tailor(friend)
    assert referral(pg_engine, "status", "friend@example.com") == "rewarded"
    assert balance(pg_engine, uid) == 1
    rid = referral(pg_engine, "id", "friend@example.com")
    assert sql(pg_engine, "SELECT reason || ':' || reference_id || ':' || idempotency_key FROM credit_transactions"
                          " WHERE user_id = :u", u=uid) == f"referral:{rid}:referral:{rid}"
    tailor(friend)  # a second tailoring pays nothing more
    assert balance(pg_engine, uid) == 1

    mine = browser.get("/api/referrals").json()
    assert (mine["rewarded"], mine["pending"], mine["total_earned"]) == (1, 0, 1)
    assert "email" not in str(mine["referrals"][0])  # the referrer never sees who


def test_reward_on_verified_signup_with_an_invitee_reward(referrer, new_browser, notices, pg_engine, monkeypatch):
    uid, _, code = referrer
    cfg(monkeypatch, trigger="on_verified_signup", reward_credits=2, invitee_reward_credits=1)
    join(new_browser, notices, code, "friend@example.com")
    assert referral(pg_engine, "status", "friend@example.com") == "rewarded"
    assert balance(pg_engine, uid) == 2
    friend_id = sql(pg_engine, "SELECT id FROM users WHERE email = 'friend@example.com'")
    assert balance(pg_engine, friend_id) == 1


def test_no_cookie_or_unknown_code_records_nothing(referrer, new_browser, notices, pg_engine):
    join(new_browser, notices, None, "a@example.com")
    join(new_browser, notices, "ZZZZZZZZ", "b@example.com")
    assert sql(pg_engine, "SELECT count(*) FROM referrals") == 0


def test_same_person_and_disposable_email_are_rejected(referrer, new_browser, notices, pg_engine, monkeypatch):
    uid, _, code = referrer
    cfg(monkeypatch, trigger="on_verified_signup")
    join(new_browser, notices, code, "a.d.a+second@gmail.com")
    join(new_browser, notices, code, "temp@mailinator.com")
    assert referral(pg_engine, "status || ':' || reason", "a.d.a+second@gmail.com") == "rejected:same_person"
    assert referral(pg_engine, "status || ':' || reason", "temp@mailinator.com") == "rejected:disposable_email"
    assert balance(pg_engine, uid) == 0


def test_a_referee_is_attributed_once(referrer, new_browser, notices, pg_engine):
    uid, _, code = referrer
    other = new_user(pg_engine, "bo@example.com")
    other_code = signed_in_as(new_browser, other).get("/api/referrals").json()["code"]
    join(new_browser, notices, code, "friend@example.com")
    friend_id = sql(pg_engine, "SELECT id FROM users WHERE email = 'friend@example.com'")

    async def again():
        engine = create_async_engine(pg_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
        async with async_sessionmaker(engine)() as db, db.begin():
            friend = await db.get(User, friend_id)
            result = await referrals.attribute(db, get_billing_config(), friend, other_code, ip_hmac=None)
        await engine.dispose()
        return result
    assert asyncio.run(again()) is None
    assert sql(pg_engine, "SELECT count(*) FROM referrals") == 1


def test_rewards_stop_at_the_monthly_cap(referrer, new_browser, notices, pg_engine, monkeypatch):
    uid, _, code = referrer
    cfg(monkeypatch, trigger="on_verified_signup", monthly_cap=2, same_ip_review_threshold=99)
    for i in range(3):
        join(new_browser, notices, code, f"f{i}@example.com")
    assert balance(pg_engine, uid) == 2
    assert referral(pg_engine, "status || ':' || reason", "f2@example.com") == "rejected:over_monthly_cap"


def test_many_signups_from_one_network_wait_for_review(referrer, new_browser, notices, pg_engine, monkeypatch,
                                                       config_override):
    uid, _, code = referrer
    config = cfg(monkeypatch, trigger="on_verified_signup", same_ip_review_threshold=3)
    config_override(config)
    for i in range(3):  # the test client always comes from the same address
        join(new_browser, notices, code, f"f{i}@example.com")
    assert balance(pg_engine, uid) == 2
    assert referral(pg_engine, "needs_review::text || ':' || reason", "f2@example.com") == "true:same_network"
    assert referral(pg_engine, "status", "f2@example.com") == "pending"


def test_admin_queue_approves_rejects_and_reverses(referrer, new_browser, notices, pg_engine, monkeypatch,
                                                  config_override):
    uid, user_browser, code = referrer
    config = cfg(monkeypatch, trigger="on_verified_signup", same_ip_review_threshold=2)
    config_override(config)
    for i in range(3):
        join(new_browser, notices, code, f"f{i}@example.com")
    assert balance(pg_engine, uid) == 1  # f0 paid; f1 and f2 wait
    admin = signed_in_as(new_browser, sql(pg_engine, "INSERT INTO users (email, email_verified_at, activated_at,"
                                                     " age_confirmed_at, terms_version, terms_accepted_at, role)"
                                                     " VALUES ('admin@example.com', now(), now(), now(), 'v1',"
                                                     " now(), 'admin') RETURNING id"))
    assert user_browser.get("/api/admin/referrals").status_code == 403
    queue = admin.get("/api/admin/referrals").json()
    assert sorted(r["referee_email"] for r in queue) == ["f1@example.com", "f2@example.com"]
    assert all(r["same_network"] >= 2 for r in queue)
    by_email = {r["referee_email"]: r["id"] for r in queue}

    assert admin.post(f"/api/admin/referrals/{by_email['f1@example.com']}/approve").status_code == 204
    assert admin.post(f"/api/admin/referrals/{by_email['f2@example.com']}/reject",
                      json={"reason": "looks like one person"}).status_code == 204
    assert balance(pg_engine, uid) == 2
    assert referral(pg_engine, "status || ':' || reason", "f2@example.com") == "rejected:looks like one person"
    assert admin.post(f"/api/admin/referrals/{by_email['f2@example.com']}/approve").status_code == 409

    paid = referral(pg_engine, "id", "f1@example.com")
    assert admin.post(f"/api/admin/referrals/{paid}/reverse", json={"reason": "fraud"}).status_code == 204
    assert admin.post(f"/api/admin/referrals/{paid}/reverse", json={"reason": "fraud"}).status_code == 409
    assert balance(pg_engine, uid) == 1
    assert referral(pg_engine, "status || ':' || reason", "f1@example.com") == "rejected:fraud"
    recent = admin.get("/api/admin/referrals?view=recent").json()
    assert len(recent) == 3


def test_live_updates_show_a_new_reward_once(referrer, new_browser, notices, pg_engine):
    uid, browser, code = referrer
    friend, _ = join(new_browser, notices, code, "friend@example.com")
    assert browser.get("/api/referrals/updates").json() == {"credits_balance": 0, "new_rewards": []}
    tailor(friend)
    updates = browser.get("/api/referrals/updates").json()
    assert updates["credits_balance"] == 1 and [r["credits"] for r in updates["new_rewards"]] == [1]
    assert browser.post("/api/referrals/updates/seen", json={"ids": [updates["new_rewards"][0]["id"]]}).status_code == 204
    assert browser.get("/api/referrals/updates").json()["new_rewards"] == []
    stranger = signed_in_as(new_browser, new_user(pg_engine, "x@example.com"))
    assert stranger.get("/api/referrals/updates").json()["new_rewards"] == []


def test_referrals_need_sign_in(client):
    assert client.get("/api/referrals").status_code == 401
    assert client.get("/api/referrals/updates").status_code == 401


# --- invite-only: the referral link is the invite ------------------------------------------------


def test_invite_only_a_referral_link_works_as_an_invite_up_to_the_limit(referrer, new_browser, notices, pg_engine,
                                                                       monkeypatch, config_override):
    monkeypatch.setenv("RT_INVITE_ONLY", "1")
    uid, browser, code = referrer
    config = cfg(monkeypatch, invites_per_user=1)
    config_override(config)
    monkeypatch.setattr("app.api.signin.get_billing_config", lambda: config)

    friend = new_browser()
    friend.cookies.set(referrals.COOKIE, code)
    post(friend, "/test/identity", {"provider": "github", "provider_account_id": "f1", "verified_email": "f1@example.com"})
    assert friend.get("/api/auth/pending").json()["has_referral_invite"] is True
    _, res = join(new_browser, notices, code, "f1@example.com", referral_invite=True, account="f1b")
    assert res.json() == {"next": "signed_in"}
    assert referral(pg_engine, "used_as_invite", "f1@example.com") is True
    assert browser.get("/api/referrals").json()["invites_left"] == 0

    late = new_browser()
    late.cookies.set(referrals.COOKIE, code)
    post(late, "/test/identity", {"provider": "github", "provider_account_id": "f2", "verified_email": "f2@example.com"})
    assert late.get("/api/auth/pending").json()["has_referral_invite"] is False
    res = post(late, "/api/auth/signup/invite", {"referral": True})
    assert (res.status_code, res.json()["detail"]) == (400, "no_invite")
    assert sql(pg_engine, "SELECT count(*) FROM users WHERE email = 'f2@example.com'") == 0


def test_invite_only_with_a_regular_invite_still_attributes(referrer, new_browser, notices, pg_engine, monkeypatch,
                                                           make_invite):
    monkeypatch.setenv("RT_INVITE_ONLY", "1")
    _, _, code = referrer
    _, res = join(new_browser, notices, code, "f@example.com", invite=make_invite())
    assert res.json() == {"next": "signed_in"}
    assert referral(pg_engine, "used_as_invite", "f@example.com") is False
