"""Behind the Next.js proxy, everything the browser sees is on the app domain.

In staging and production the browser only talks to the frontend (RT_PUBLIC_URL); Next
rewrites /api/* to BACKEND_URL, a private host the browser never sees. So these requests
arrive with the backend's internal Host (and an X-Forwarded-Host we must not trust), and
every cookie, CSRF check, OAuth redirect URI, magic link and redirect must still be built
from RT_PUBLIC_URL alone."""

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from tests.test_auth_session import set_cookie_headers

APP = "https://app.example.com"
INTERNAL = "http://backend.internal:8000"
PROXY_HEADERS = {"Origin": APP, "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "http"}


@pytest.fixture
def behind_proxy(api_app, monkeypatch):
    monkeypatch.setenv("RT_PUBLIC_URL", APP)
    monkeypatch.setenv("RT_AUTH_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id.apps")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "github-client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "github-secret")
    with TestClient(api_app, base_url=INTERNAL, headers=PROXY_HEADERS) as client:
        yield client


def forwarded(client) -> dict[str, str]:
    """The browser's cookies as Next forwards them. The browser holds them for the https app
    domain; the proxy hop is plain http, where a client wouldn't send Secure cookies itself."""
    return {"Cookie": "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)}


def csrf(client) -> dict[str, str]:
    token = client.get("/api/auth/csrf", headers=forwarded(client)).json()["csrf_token"]
    return {"X-CSRF-Token": token} | forwarded(client)


def test_cookies_are_host_only_on_the_app_domain(behind_proxy, user_id):
    cookies = set_cookie_headers(behind_proxy.post(f"/test/login/{user_id}"))
    assert set(cookies) == {"__Host-rt_session", "__Host-rt_csrf"}
    for header in cookies.values():
        lowered = header.lower()
        assert "secure" in lowered and "path=/" in lowered and "domain" not in lowered
        assert "backend.internal" not in lowered and "evil.example" not in lowered


def test_csrf_accepts_only_the_app_origin(behind_proxy, user_id):
    behind_proxy.post(f"/test/login/{user_id}")
    token = csrf(behind_proxy)
    for origin in (INTERNAL, "https://evil.example", "http://app.example.com"):
        assert behind_proxy.post("/api/auth/logout", headers=token | {"Origin": origin}).status_code == 403
    assert behind_proxy.post("/api/auth/logout", headers=token).status_code == 204


@pytest.mark.parametrize("provider", ["google", "github"])
def test_oauth_redirect_uri_is_on_the_app_domain(behind_proxy, provider):
    res = behind_proxy.get(f"/api/auth/{provider}/start", follow_redirects=False)
    assert res.status_code == 302
    query = parse_qs(urlsplit(res.headers["location"]).query)
    assert query["redirect_uri"] == [f"{APP}/api/auth/{provider}/callback"]
    flow = set_cookie_headers(res)["__Host-rt_oauth"].lower()
    assert "secure" in flow and "domain" not in flow
    # A failed callback goes back to a page on whatever domain the browser is on.
    failed = behind_proxy.get(f"/api/auth/{provider}/callback", params={"state": "x", "code": "y"},
                              follow_redirects=False)
    assert failed.status_code == 302 and failed.headers["location"].startswith("/")


def test_magic_link_is_on_the_app_domain(behind_proxy, outbox, user_id):
    res = behind_proxy.post("/api/auth/email/start", json={"email": "ada@example.com"}, headers=csrf(behind_proxy))
    assert res.status_code == 202
    assert outbox[-1].link.startswith(f"{APP}/auth/email#token=")
