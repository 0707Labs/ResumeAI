"""Session core: cookies, rotation, expiry, CSRF, rate limits, event logs.

These tests sign in through the test-only /test/login route (tests/conftest.py)."""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.auth.ratelimit import SlidingWindow
from app.auth.sessions import ABSOLUTE
from app.auth.tokens import hash_token
from app.db.models import AuthSession
from tests.conftest import ORIGIN

NOW = datetime.now(UTC)


def sign_in(client, user_id) -> None:
    assert client.post(f"/test/login/{user_id}").status_code == 200


def session_rows(pg_engine) -> list:
    with pg_engine.connect() as conn:
        return conn.execute(select(AuthSession)).all()


def set_cookie_headers(res) -> dict[str, str]:
    return {h.split("=", 1)[0]: h for h in res.headers.get_list("set-cookie")}


def csrf_headers(client) -> dict[str, str]:
    return {"X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]}


# --- sessions --------------------------------------------------------------------


def test_me_requires_a_session(client):
    res = client.get("/api/me")
    assert res.status_code == 401 and res.json()["detail"] == "not_signed_in"


def test_sign_in_sets_httponly_lax_cookie_and_stores_only_a_hash(client, user_id, pg_engine):
    res = client.post(f"/test/login/{user_id}")
    cookies = set_cookie_headers(res)
    session = cookies["rt_session"].lower()
    assert "httponly" in session and "samesite=lax" in session and "path=/" in session
    assert "httponly" not in cookies["rt_csrf"].lower()  # our JS echoes it back

    token = client.cookies["rt_session"]
    [row] = session_rows(pg_engine)
    assert row.session_token_hash == hash_token(token) != token

    me = client.get("/api/me").json()
    assert me == {"id": str(user_id), "email": "ada@example.com", "name": None, "capabilities": [], "onboarded": False, "avatar_url": None,
                  "role": "user", "status": "active"}


def test_sign_in_rotates_session_and_csrf(client, user_id, pg_engine):
    sign_in(client, user_id)
    first, first_csrf = client.cookies["rt_session"], client.cookies["rt_csrf"]
    sign_in(client, user_id)
    second = client.cookies["rt_session"]
    assert second != first and client.cookies["rt_csrf"] != first_csrf
    assert [r.session_token_hash for r in session_rows(pg_engine)] == [hash_token(second)]

    # Delete first: httpx2 >= 2.16 keeps the server's cookie beside a domain-less one.
    client.cookies.delete("rt_session")
    client.cookies.set("rt_session", first)
    assert client.get("/api/me").status_code == 401


def test_expired_session_is_rejected_and_removed(client, user_id, pg_engine):
    sign_in(client, user_id)
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE auth_sessions SET expires_at = now() - interval '1 second'"))
    assert client.get("/api/me").status_code == 401
    assert session_rows(pg_engine) == []


def test_session_slides_but_never_past_the_absolute_cap(client, user_id, pg_engine):
    sign_in(client, user_id)
    created = NOW - ABSOLUTE + timedelta(days=2)
    with pg_engine.begin() as conn:
        conn.execute(text(
            "UPDATE auth_sessions SET created_at = :c, last_seen_at = :c, expires_at = now() + interval '1 day'"
        ), {"c": created})
    assert client.get("/api/me").status_code == 200
    [row] = session_rows(pg_engine)
    assert row.expires_at == created + ABSOLUTE  # capped, not now + 30 days
    assert row.last_seen_at > created


def test_suspended_user_is_refused(client, user_id, pg_engine):
    sign_in(client, user_id)
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET status = 'suspended'"))
    res = client.get("/api/me")
    assert res.status_code == 403 and res.json()["detail"] == "account_suspended"


def test_deleted_user_session_is_dropped(client, user_id, pg_engine):
    sign_in(client, user_id)
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET deleted_at = now()"))
    assert client.get("/api/me").status_code == 401
    assert session_rows(pg_engine) == []


# --- logout and CSRF ------------------------------------------------------------------


def test_logout_deletes_session_and_clears_cookies(client, user_id, pg_engine):
    sign_in(client, user_id)
    res = client.post("/api/auth/logout", headers=csrf_headers(client))
    assert res.status_code == 204
    cleared = set_cookie_headers(res)
    assert 'rt_session=""' in cleared["rt_session"] and "max-age=0" in cleared["rt_session"].lower()
    assert session_rows(pg_engine) == []
    assert client.get("/api/me").status_code == 401


def test_logout_without_csrf_token_is_refused(client, user_id, pg_engine):
    sign_in(client, user_id)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert len(session_rows(pg_engine)) == 1


def test_logout_from_another_origin_is_refused(client, user_id, pg_engine):
    sign_in(client, user_id)
    token = csrf_headers(client)
    res = client.post("/api/auth/logout", headers=token | {"Origin": "https://evil.example"})
    assert res.status_code == 403 and res.json()["detail"] == "csrf_failed"
    assert len(session_rows(pg_engine)) == 1


def test_referer_counts_when_origin_is_absent(client):
    token = csrf_headers(client)
    del client.headers["Origin"]
    assert client.post("/api/auth/logout", headers=token).status_code == 403
    ok = client.post("/api/auth/logout", headers=token | {"Referer": f"{ORIGIN}/account"})
    assert ok.status_code == 204


def test_csrf_endpoint_is_stable_until_rotation(client):
    first = client.get("/api/auth/csrf").json()["csrf_token"]
    assert client.get("/api/auth/csrf").json()["csrf_token"] == first == client.cookies["rt_csrf"]


def test_https_origin_uses_host_prefixed_secure_cookies(client, user_id, monkeypatch):
    monkeypatch.setenv("RT_PUBLIC_URL", "https://app.example")
    res = client.post(f"/test/login/{user_id}")
    cookies = set_cookie_headers(res)
    assert set(cookies) == {"__Host-rt_session", "__Host-rt_csrf"}
    assert all("secure" in h.lower() and "domain" not in h.lower() for h in cookies.values())


# --- rate limits and logs ------------------------------------------------------------


def test_sliding_window_limits_and_recovers():
    now = [0.0]
    window = SlidingWindow(clock=lambda: now[0])
    assert all(window.hit("k", 3, 60) is None for _ in range(3))
    assert window.hit("k", 3, 60) == pytest.approx(60)
    assert window.hit("other", 3, 60) is None  # keys are independent
    now[0] = 60.5
    assert window.hit("k", 3, 60) is None


def test_auth_endpoint_is_rate_limited(client):
    headers = csrf_headers(client)
    # Logout clears the CSRF cookie, so later calls are 403s; they still count.
    codes = [client.post("/api/auth/logout", headers=headers).status_code for _ in range(31)]
    assert codes[0] == 204 and 429 not in codes[:30] and codes[30] == 429


def test_auth_events_carry_no_pii(client, user_id, caplog):
    caplog.set_level(logging.INFO, logger="app.auth.events")
    sign_in(client, user_id)
    token = client.cookies["rt_session"]
    client.post("/api/auth/logout", headers=csrf_headers(client))
    client.post("/api/auth/logout")  # csrf_rejected

    lines = [r.getMessage() for r in caplog.records if r.name == "app.auth.events"]
    events = [json.loads(line) for line in lines]
    assert [e["event"] for e in events] == ["login", "logout", "csrf_rejected"]
    assert events[0] == {"event": "login", "outcome": "ok", "provider": "google", "user_id": str(user_id)}
    blob = "\n".join(lines)
    for secret in ("ada@example.com", token, hash_token(token), "testclient"):
        assert secret not in blob


def test_provider_availability_follows_configuration(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    assert client.get("/api/auth/providers").json() == {"google": True, "github": False, "email": True}


def test_dev_rate_limit_scale_only_applies_on_localhost(monkeypatch):
    from app.auth.ratelimit import scaled

    assert scaled(5) == 5
    monkeypatch.setenv("RT_DEV_RATE_LIMIT_SCALE", "10")
    assert scaled(5) == 50  # RT_PUBLIC_URL defaults to http://localhost:3000
    monkeypatch.setenv("RT_PUBLIC_URL", "https://resume.0707labs.com")
    assert scaled(5) == 5
    monkeypatch.setenv("RT_PUBLIC_URL", "http://localhost:3000")
    monkeypatch.setenv("RT_DEV_RATE_LIMIT_SCALE", "100000")
    assert scaled(5) == 500  # capped at x100
