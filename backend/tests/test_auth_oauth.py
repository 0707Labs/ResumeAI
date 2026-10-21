"""Google and GitHub sign-in against mocked providers.

The OAuth module's HTTP goes through an httpx2 MockTransport: a request to any
URL a test didn't mock fails, so nothing here touches the network. Google
id_tokens are signed with a test RSA key whose JWKS the mock serves."""

import base64
import hashlib
import json
import logging
import time
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey
from sqlalchemy import text

from app.auth import oauth
from tests.test_auth_signin import consent, count, post, scalar

GOOGLE_ID, GITHUB_ID = "google-client-id.apps", "github-client-id"
SIGNING_KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", GOOGLE_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("GITHUB_CLIENT_ID", GITHUB_ID)
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "github-secret")
    oauth._jwks.update(keys=None, at=0.0)


class Route:
    def __init__(self):
        self.calls: list[httpx2.Request] = []
        self.return_value: httpx2.Response | None = None
        self.side_effect: Exception | None = None

    def respond(self, **kw) -> "Route":
        self.return_value = httpx2.Response(200, **kw)
        return self


class FakeProviders:
    """Just enough of a router: mock.post(url).respond(json=...), route.calls[-1]."""

    def __init__(self):
        self.routes: dict[tuple[str, str], Route] = {}

    def _route(self, method: str, url: str) -> Route:
        return self.routes.setdefault((method, url), Route())

    def get(self, url: str) -> Route:
        return self._route("GET", url)

    def post(self, url: str) -> Route:
        return self._route("POST", url)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url.copy_with(query=None))
        route = self.routes.get((request.method, url))
        if route is None or (route.return_value is None and route.side_effect is None):
            raise AssertionError(f"unmocked request: {request.method} {url}")
        request.read()
        route.calls.append(request)
        if route.side_effect is not None:
            raise route.side_effect
        return route.return_value


@pytest.fixture
def mock():
    fake = FakeProviders()
    fake.get(oauth.GOOGLE_JWKS_URL).respond(json={"keys": [SIGNING_KEY.as_dict(private=False)]})
    oauth.set_transport(httpx2.MockTransport(fake.handle))
    yield fake
    oauth.set_transport(None)


def start(client, provider, next_path=None) -> dict[str, str]:
    params = {"next": next_path} if next_path else {}
    res = client.get(f"/api/auth/{provider}/start", params=params, follow_redirects=False)
    assert res.status_code == 302
    return {k: v[0] for k, v in parse_qs(urlsplit(res.headers["location"]).query).items()}


def callback(client, provider, **params):
    return client.get(f"/api/auth/{provider}/callback", params=params, follow_redirects=False)


def id_token(nonce, *, sub="g-123", email="new.person@example.com", verified=True, key=SIGNING_KEY,
             **overrides) -> str:
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": GOOGLE_ID, "sub": sub, "iat": now,
              "exp": now + 300, "nonce": nonce, "email": email, "email_verified": verified} | overrides
    return jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)


def google(client, mock, next_path=None, **token_kw):
    """Run a Google sign-in to the callback; returns the callback response."""
    q = start(client, "google", next_path)
    mock.post(oauth.PROVIDERS["google"].token_url).respond(
        json={"access_token": "ya29.x", "token_type": "Bearer", "expires_in": 3600,
              "id_token": id_token(q["nonce"], **token_kw)})
    return callback(client, "google", code="auth-code", state=q["state"])


def github(client, mock, emails, user_id=4242, profile_email=None):
    q = start(client, "github")
    mock.post(oauth.PROVIDERS["github"].token_url).respond(
        json={"access_token": "gho_x", "token_type": "bearer", "scope": "read:user,user:email"})
    mock.get(f"{oauth.GITHUB_API}/user").respond(json={"id": user_id, "login": "ada", "email": profile_email})
    mock.get(f"{oauth.GITHUB_API}/user/emails").respond(json=emails)
    return callback(client, "github", code="auth-code", state=q["state"])


def primary(email="new.person@example.com", verified=True):
    return [{"email": "other@example.com", "primary": False, "verified": True},
            {"email": email, "primary": True, "verified": verified}]


def where(res) -> str:
    assert res.status_code == 302, res.text
    return res.headers["location"]


# --- start ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("provider,scope", [("google", "openid email profile"), ("github", "read:user user:email")])
def test_start_requests_minimal_scopes_with_state_and_pkce(client, provider, scope):
    q = start(client, provider)
    assert q["scope"] == scope
    assert q["response_type"] == "code"
    assert q["redirect_uri"] == f"http://localhost:3000/api/auth/{provider}/callback"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert len(q["state"]) >= 40
    assert ("nonce" in q) == (provider == "google")
    cookie = next(h for h in client.get(f"/api/auth/{provider}/start", follow_redirects=False)
                  .headers.get_list("set-cookie") if h.startswith("rt_oauth="))
    assert "httponly" in cookie.lower() and "max-age=600" in cookie.lower()


def test_unconfigured_provider_is_unavailable(client, monkeypatch):
    monkeypatch.delenv("GITHUB_CLIENT_SECRET")
    res = client.get("/api/auth/github/start", follow_redirects=False)
    assert where(res) == "/signin?error=provider_unavailable"


def test_pkce_verifier_is_sent_and_matches_the_challenge(client, mock):
    q = start(client, "google")
    token = mock.post(oauth.PROVIDERS["google"].token_url).respond(
        json={"access_token": "x", "token_type": "Bearer", "id_token": id_token(q["nonce"])})
    callback(client, "google", code="auth-code", state=q["state"])
    sent = parse_qs(token.calls[-1].content.decode())
    verifier = sent["code_verifier"][0]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == q["code_challenge"] and sent["code"] == ["auth-code"]
    assert sent["redirect_uri"] == ["http://localhost:3000/api/auth/google/callback"]


@pytest.mark.parametrize("next_path,expected", [
    ("/app/review", "/app/review"), ("/review", "/app"), ("/account/linked", "/account/linked"), ("/app", "/app"), ("/", "/"),
    (None, "/app"), ("//evil.example", "/app"), ("https://evil.example", "/app"), ("/\\evil.example", "/app"),
    ("/signin", "/app"), ("/../admin", "/app"), ("/appx", "/app"),
])
def test_post_sign_in_destination_is_allowlisted(next_path, expected):
    assert oauth.safe_next(next_path) == expected


# --- invite gate ---------------------------------------------------------------------------------


def test_new_oauth_user_without_invite_cannot_get_an_account(client, mock, notices, pg_engine):
    assert where(google(client, mock)) == "/signup/invite"
    assert count(pg_engine, "users") == 0 and count(pg_engine, "accounts") == 0
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/auth/pending").json()["email"] == "new.person@example.com"
    assert post(client, "/api/auth/signup/invite", {"code": "AAAA-BBBB-CCCC"}).json()["detail"] == "no_invite"
    assert post(client, "/api/auth/signup/complete", consent(notices)).json()["detail"] == "invite_required"
    assert count(pg_engine, "users") == 0


def test_new_oauth_user_with_invite_is_created_once_and_invite_cannot_be_reused(
        new_browser, mock, notices, make_invite, pg_engine):
    code = make_invite()
    first = new_browser()
    assert where(google(first, mock)) == "/signup/invite"
    assert post(first, "/api/auth/signup/invite", {"code": code}).json() == {"next": "consent"}
    assert post(first, "/api/auth/signup/complete", consent(notices)).json() == {"next": "signed_in"}
    assert first.get("/api/me").json()["email"] == "new.person@example.com"
    assert count(pg_engine, "users") == 1
    assert count(pg_engine, "accounts", "provider = 'google' AND provider_account_id = 'g-123'") == 1

    # Signing in again goes straight in: no second user.
    assert where(google(first, mock, next_path="/app/review")) == "/app/review"
    assert count(pg_engine, "users") == 1

    other = new_browser()
    assert where(github(other, mock, primary("someone.else@example.com"))) == "/signup/invite"
    assert post(other, "/api/auth/signup/invite", {"code": code}).json()["detail"] == "no_invite"
    assert count(pg_engine, "users") == 1


def test_existing_user_signs_in_directly_and_session_rotates(client, mock, user_id, pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO accounts (user_id, provider, provider_account_id, email_at_link)"
                          " VALUES (:u, 'google', 'g-ada', 'ada@example.com')"), {"u": user_id})
    assert where(google(client, mock, sub="g-ada", email="ada@example.com")) == "/app"
    first = client.cookies["rt_session"]
    assert client.get("/api/me").json()["id"] == str(user_id)
    google(client, mock, sub="g-ada", email="ada@example.com")
    assert client.cookies["rt_session"] != first
    assert count(pg_engine, "auth_sessions") == 1


def test_suspended_user_is_sent_back_to_login(client, mock, user_id, pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET status = 'suspended'"))
    assert where(google(client, mock, email="ada@example.com")) == "/signin?error=account_unavailable"
    assert client.get("/api/me").status_code == 401


# --- linking -------------------------------------------------------------------------------------


def test_same_verified_email_via_second_provider_links_to_the_same_user(client, mock, user_id, pg_engine):
    assert where(google(client, mock, sub="g-ada", email="Ada@Example.com")) == "/app"
    assert where(github(client, mock, primary("ada@example.com"))) == "/app"
    linked = scalar(pg_engine, "SELECT array_agg(provider ORDER BY provider) FROM accounts WHERE user_id = :u",
                    u=user_id)
    assert linked == ["github", "google"] and count(pg_engine, "users") == 1


def test_unverified_google_email_never_auto_links(client, mock, user_id, pg_engine):
    assert where(google(client, mock, email="ada@example.com", verified=False)) == "/signup/verify-email"
    assert count(pg_engine, "accounts") == 0
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize("verified", ["true", 1, None])
def test_only_a_boolean_true_email_verified_counts(client, mock, user_id, pg_engine, verified):
    assert where(google(client, mock, email="ada@example.com", verified=verified)) == "/signup/verify-email"
    assert count(pg_engine, "accounts") == 0


def test_github_uses_primary_verified_email_not_profile_or_secondary(client, mock, user_id, pg_engine):
    emails = [{"email": "ada@example.com", "primary": False, "verified": True},
              {"email": "ada.primary@example.com", "primary": True, "verified": False}]
    res = github(client, mock, emails, profile_email="ada@example.com")
    assert where(res) == "/signup/verify-email"
    assert count(pg_engine, "accounts") == 0


# --- GitHub without a verified email ---------------------------------------------------------


def test_github_without_verified_email_requires_email_verification(client, mock, outbox, notices, make_invite,
                                                                  pg_engine):
    assert where(github(client, mock, [])) == "/signup/verify-email"
    code = make_invite()
    assert post(client, "/api/auth/signup/invite", {"code": code}).json()["detail"] == "email_unverified"

    post(client, "/api/auth/pending/email", {"email": "new.person@example.com"})
    assert post(client, "/api/auth/email/verify", {"token": outbox.last_token()}).json() == {"next": "invite"}
    post(client, "/api/auth/signup/invite", {"code": code})
    assert post(client, "/api/auth/signup/complete", consent(notices)).json() == {"next": "signed_in"}
    assert scalar(pg_engine, "SELECT provider_account_id FROM accounts WHERE provider = 'github'") == "4242"


# --- state, replay and provider failures -------------------------------------------------------


def test_state_mismatch_is_rejected(client, mock):
    start(client, "google")
    res = callback(client, "google", code="auth-code", state="forged")
    assert where(res) == "/signin?error=oauth_state"


def test_callback_without_flow_cookie_is_rejected(new_browser, mock):
    q = start(new_browser(), "google")
    assert where(callback(new_browser(), "google", code="c", state=q["state"])) == "/signin?error=oauth_state"


def test_callback_state_cannot_be_replayed(client, mock, notices):
    q = start(client, "google")
    mock.post(oauth.PROVIDERS["google"].token_url).respond(
        json={"access_token": "x", "token_type": "Bearer", "id_token": id_token(q["nonce"])})
    assert where(callback(client, "google", code="c", state=q["state"])) == "/signup/invite"
    assert where(callback(client, "google", code="c", state=q["state"])) == "/signin?error=oauth_state"


def test_state_from_one_provider_is_rejected_by_the_other(client, mock):
    q = start(client, "google")
    assert where(callback(client, "github", code="c", state=q["state"])) == "/signin?error=oauth_state"


def test_user_cancelling_at_the_provider(client):
    q = start(client, "github")
    res = callback(client, "github", error="access_denied", state=q["state"])
    assert where(res) == "/signin?error=cancelled"


@pytest.mark.parametrize("bad", [
    {"nonce": "someone-elses"},
    {"aud": "another-client"},
    {"iss": "https://evil.example"},
    {"exp": int(time.time()) - 10},
    {"key": OTHER_KEY},
])
def test_invalid_google_id_token_is_rejected(client, mock, pg_engine, bad):
    q = start(client, "google")
    nonce = bad.pop("nonce", q["nonce"])
    mock.post(oauth.PROVIDERS["google"].token_url).respond(
        json={"access_token": "x", "token_type": "Bearer", "id_token": id_token(nonce, **bad)})
    assert where(callback(client, "google", code="c", state=q["state"])) == "/signin?error=provider_unavailable"
    assert count(pg_engine, "pending_auth") == 0


@pytest.mark.parametrize("failure", [
    httpx2.Response(500), httpx2.Response(200, json={"error": "bad_verification_code"}),
    httpx2.ConnectTimeout("slow"),
])
def test_provider_failure_is_reported_as_unavailable(client, mock, failure):
    q = start(client, "github")
    route = mock.post(oauth.PROVIDERS["github"].token_url)
    route.side_effect = failure if isinstance(failure, Exception) else None
    if not isinstance(failure, Exception):
        route.return_value = failure
    assert where(callback(client, "github", code="c", state=q["state"])) == "/signin?error=provider_unavailable"


def test_oauth_logs_carry_no_email_or_provider_ids(client, mock, caplog):
    caplog.set_level(logging.INFO, logger="app.auth.events")
    github(client, mock, primary())
    lines = [r.getMessage() for r in caplog.records if r.name == "app.auth.events"]
    assert [json.loads(line)["event"] for line in lines] == ["oauth_started", "pending_created"]
    blob = "\n".join(lines)
    for secret in ("new.person@example.com", "4242", "auth-code", "gho_x"):
        assert secret not in blob
