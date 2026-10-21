"""/account: listing, connecting and disconnecting login methods; account deletion."""

import asyncio
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.account import AccountError, unlink
from tests.test_auth_oauth import callback, google, id_token, mock, providers, where  # noqa: F401 (fixtures)
from tests.test_auth_signin import count, csrf, magic_link, post, scalar


def add_account(pg_engine, user_id, provider, pid, email="ada@example.com") -> uuid.UUID:
    with pg_engine.begin() as conn:
        return conn.execute(text(
            "INSERT INTO accounts (user_id, provider, provider_account_id, email_at_link)"
            " VALUES (:u, :p, :i, :e) RETURNING id"), {"u": user_id, "p": provider, "i": pid, "e": email}
        ).scalar_one()


def add_user(pg_engine, email) -> uuid.UUID:
    with pg_engine.begin() as conn:
        return conn.execute(text(
            "INSERT INTO users (email, email_verified_at, activated_at, age_confirmed_at, terms_version,"
            " terms_accepted_at) VALUES (:e, now(), now(), now(), 'v1', now()) RETURNING id"), {"e": email}
        ).scalar_one()


@pytest.fixture
def ada(client, user_id, pg_engine):
    """Ada, signed in, with email sign-in as her only login method."""
    email_account = add_account(pg_engine, user_id, "email", "ada@example.com")
    assert client.post(f"/test/login/{user_id}").status_code == 200
    return {"id": user_id, "email_account": email_account}


def delete(client, path):
    return client.delete(path, headers=csrf(client))


# --- listing and unlinking ------------------------------------------------------------------


def test_providers_lists_linked_methods(client, ada, pg_engine):
    add_account(pg_engine, ada["id"], "google", "g-ada")
    body = client.get("/api/account/providers").json()
    assert [a["provider"] for a in body["accounts"]] == ["email", "google"]
    assert all(a["email"] == "ada@example.com" for a in body["accounts"])
    assert body["can_unlink"] is True
    assert body["available"] == {"google": True, "github": True, "email": True}


def test_providers_needs_a_session(client):
    assert client.get("/api/account/providers").status_code == 401


def test_cannot_unlink_the_last_login_method(client, ada, pg_engine):
    assert client.get("/api/account/providers").json()["can_unlink"] is False
    res = delete(client, f"/api/account/providers/{ada['email_account']}")
    assert res.status_code == 409 and res.json()["detail"] == "last_login_method"
    assert count(pg_engine, "accounts") == 1


def test_unlink_one_of_two_then_the_last_is_kept(client, ada, pg_engine):
    google_account = add_account(pg_engine, ada["id"], "google", "g-ada")
    assert delete(client, f"/api/account/providers/{ada['email_account']}").status_code == 204
    assert scalar(pg_engine, "SELECT provider FROM accounts") == "google"
    assert delete(client, f"/api/account/providers/{google_account}").status_code == 409
    assert count(pg_engine, "accounts") == 1


def test_cannot_unlink_someone_elses_account(client, ada, pg_engine):
    bo = add_user(pg_engine, "bo@example.com")
    bo_google = add_account(pg_engine, bo, "google", "g-bo", "bo@example.com")
    add_account(pg_engine, bo, "github", "77", "bo@example.com")
    assert delete(client, f"/api/account/providers/{bo_google}").status_code == 404
    assert count(pg_engine, "accounts", f"user_id = '{bo}'") == 2


def test_unlink_requires_csrf(client, ada, pg_engine):
    add_account(pg_engine, ada["id"], "google", "g-ada")
    assert client.delete(f"/api/account/providers/{ada['email_account']}").status_code == 403
    assert count(pg_engine, "accounts") == 2


def test_concurrent_unlinks_leave_one_login_method(pg_url, pg_engine, api_app, user_id):
    accounts = [add_account(pg_engine, user_id, "email", "ada@example.com"),
                add_account(pg_engine, user_id, "google", "g-ada")]

    async def race():
        engine = create_async_engine(pg_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def attempt(account_id):
            async with sessions() as db:
                try:
                    return await unlink(db, user_id, account_id)
                except AccountError as exc:
                    return exc.code
        try:
            return await asyncio.gather(*(attempt(a) for a in accounts))
        finally:
            await engine.dispose()

    results = asyncio.run(race())
    assert results.count("last_login_method") == 1
    assert count(pg_engine, "accounts") == 1


# --- connecting Google / GitHub ---------------------------------------------------------------


def link_google(client, mock, **kw):
    q = start_link(client, "google")
    mock.post("https://oauth2.googleapis.com/token").respond(
        json={"access_token": "x", "token_type": "Bearer",
              "id_token": id_token(q["nonce"], **kw)})
    return callback(client, "google", code="c", state=q["state"])


def start_link(client, provider):
    res = client.get(f"/api/auth/{provider}/start", params={"intent": "link"}, follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"].startswith("https://"), res.headers["location"]
    return {k: v[0] for k, v in parse_qs(urlsplit(res.headers["location"]).query).items()}


def test_connect_google_with_a_different_email(client, mock, ada, pg_engine, new_browser):
    before = client.cookies["rt_session"]
    res = link_google(client, mock, sub="g-work", email="ada.work@example.com")
    assert where(res) == "/account?linked=google"
    assert client.cookies["rt_session"] != before  # rotated on link
    assert scalar(pg_engine, "SELECT user_id FROM accounts WHERE provider = 'google'") == ada["id"]
    assert scalar(pg_engine, "SELECT email_at_link FROM accounts WHERE provider = 'google'") == "ada.work@example.com"

    # Later, Google alone signs Ada in.
    fresh = new_browser()
    assert where(google(fresh, mock, sub="g-work", email="ada.work@example.com")) == "/app"
    assert fresh.get("/api/me").json()["id"] == str(ada["id"])


def test_connect_identity_owned_by_someone_else_is_refused(client, mock, ada, pg_engine):
    bo = add_user(pg_engine, "bo@example.com")
    add_account(pg_engine, bo, "google", "g-bo", "bo@example.com")
    res = link_google(client, mock, sub="g-bo", email="bo@example.com")
    assert where(res) == "/account?error=already_linked_elsewhere"
    assert scalar(pg_engine, "SELECT user_id FROM accounts WHERE provider = 'google'") == bo


def test_connect_needs_a_signed_in_user(client):
    res = client.get("/api/auth/google/start", params={"intent": "link"}, follow_redirects=False)
    assert where(res) == "/signin?error=not_signed_in"


def test_connect_needs_a_verified_email(client, mock, ada, pg_engine):
    q = start_link(client, "github")
    mock.post("https://github.com/login/oauth/access_token").respond(
        json={"access_token": "gho_x", "token_type": "bearer"})
    mock.get("https://api.github.com/user").respond(json={"id": 4242})
    mock.get("https://api.github.com/user/emails").respond(json=[])
    assert where(callback(client, "github", code="c", state=q["state"])) == "/account?error=email_unverified"
    assert count(pg_engine, "accounts", "provider = 'github'") == 0


def test_connect_is_refused_if_a_different_user_signed_in_meanwhile(client, mock, ada, pg_engine):
    q = start_link(client, "google")
    bo = add_user(pg_engine, "bo@example.com")
    client.post(f"/test/login/{bo}")
    mock.post("https://oauth2.googleapis.com/token").respond(
        json={"access_token": "x", "token_type": "Bearer",
              "id_token": id_token(q["nonce"])})
    assert where(callback(client, "google", code="c", state=q["state"])) == "/account?error=not_signed_in"
    assert count(pg_engine, "accounts", "provider = 'google'") == 0


# --- adding email sign-in ---------------------------------------------------------------------


def test_add_email_sign_in_by_magic_link(client, outbox, user_id, pg_engine, new_browser):
    add_account(pg_engine, user_id, "google", "g-ada")
    client.post(f"/test/login/{user_id}")
    assert post(client, "/api/account/email/link", {"email": "ada.home@example.com"}).status_code == 202
    assert outbox[-1].to == "ada.home@example.com"
    assert post(client, "/api/auth/email/verify", {"token": outbox.last_token()}).json() == {"next": "linked"}
    assert scalar(pg_engine, "SELECT user_id FROM accounts WHERE provider = 'email'") == user_id

    fresh = new_browser()
    assert magic_link(fresh, outbox, "ada.home@example.com").json() == {"next": "signed_in"}
    assert fresh.get("/api/me").json()["id"] == str(user_id)


def test_email_link_only_works_for_the_user_who_asked(new_browser, outbox, user_id, pg_engine):
    ada_browser, bo_browser = new_browser(), new_browser()
    add_account(pg_engine, user_id, "google", "g-ada")
    ada_browser.post(f"/test/login/{user_id}")
    bo = add_user(pg_engine, "bo@example.com")
    bo_browser.post(f"/test/login/{bo}")

    post(ada_browser, "/api/account/email/link", {"email": "ada.home@example.com"})
    token = outbox.last_token()
    wrong = post(bo_browser, "/api/auth/email/verify", {"token": token})
    assert wrong.status_code == 400 and wrong.json()["detail"] == "wrong_account"
    assert count(pg_engine, "accounts", "provider = 'email'") == 0
    assert post(ada_browser, "/api/auth/email/verify", {"token": token}).json() == {"next": "linked"}


def test_cannot_add_another_users_email(client, outbox, ada, pg_engine):
    add_user(pg_engine, "bo@example.com")
    post(client, "/api/account/email/link", {"email": "bo@example.com"})
    res = post(client, "/api/auth/email/verify", {"token": outbox.last_token()})
    assert res.status_code == 409 and res.json()["detail"] == "already_linked_elsewhere"


# --- deletion ------------------------------------------------------------------------------------


def test_account_deletion_removes_linked_provider_records(client, mock, outbox, ada, notices, pg_engine,
                                                         new_browser):
    add_account(pg_engine, ada["id"], "google", "g-ada")
    add_account(pg_engine, ada["id"], "github", "4242")
    with pg_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO consent_records (user_id, subject_ref, notice_id, purpose, action, method)"
            " VALUES (:u, 'ref', :n, 'service', 'granted', 'signup')"), {"u": ada["id"], "n": notices["service"]})
    other = new_browser()
    post(other, "/api/auth/email/start", {"email": "ada@example.com"})  # an outstanding sign-in link

    assert post(client, "/api/account/delete", {"confirm": False}).status_code == 422
    res = post(client, "/api/account/delete", {"confirm": True})
    assert res.status_code == 204

    assert count(pg_engine, "accounts") == 0
    assert count(pg_engine, "auth_sessions") == 0
    assert count(pg_engine, "email_tokens") == 0
    assert scalar(pg_engine, "SELECT deleted_at IS NOT NULL FROM users") is True
    assert scalar(pg_engine, "SELECT action FROM current_consents WHERE purpose = 'service'") == "withdrawn"
    assert client.get("/api/me").status_code == 401

    # The old link is dead, and Google now counts as a brand-new person (invite gate).
    assert post(other, "/api/auth/email/verify", {"token": outbox.last_token()}).json()["detail"] == "link_invalid"
    assert where(google(new_browser(), mock, sub="g-ada", email="ada@example.com")) == "/signup/invite"
    assert count(pg_engine, "accounts") == 0


def test_account_deletion_requires_csrf(client, ada, pg_engine):
    assert client.post("/api/account/delete", json={"confirm": True}).status_code == 403
    assert count(pg_engine, "accounts") == 1
