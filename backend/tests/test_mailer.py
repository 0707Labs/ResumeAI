"""Magic-link mailers. SES goes through an httpx2 MockTransport: no test reaches AWS."""

import json
import logging
from datetime import UTC, datetime

import httpx2
import pytest

from app.auth import mailer
from app.auth.mailer import Mail, MailerError, OutboxMailer, SesMailer, get_mailer, magic_link_mail, sigv4_headers

TO = "ada@example.com"
TOKEN = "tok_secret_123"
SES_ENV = {
    "RT_MAILER": "ses",
    "RT_MAIL_FROM": "Resume Tailor <no-reply@mail.example.com>",
    "AWS_ACCESS_KEY_ID": "AKIDTEST",
    "AWS_SECRET_ACCESS_KEY": "secret-test",
}


class FakeSes:
    def __init__(self, response: httpx2.Response | None = None):
        self.calls: list[httpx2.Request] = []
        self.response = response or httpx2.Response(200, json={"MessageId": "m-1"})

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        return self.response


@pytest.fixture
def fake_ses():
    fake = FakeSes()
    mailer.set_transport(httpx2.MockTransport(fake.handle))
    yield fake
    mailer.set_transport(None)


@pytest.fixture
def ses_env(monkeypatch):
    for k, v in SES_ENV.items():
        monkeypatch.setenv(k, v)
    for k in ("AWS_SESSION_TOKEN", "RT_SES_REGION", "RT_SES_CONFIGURATION_SET"):
        monkeypatch.delenv(k, raising=False)


def a_mail() -> Mail:
    return magic_link_mail(TO, TOKEN, "login")


# --- configuration ---------------------------------------------------------------------


def test_outbox_is_the_default(monkeypatch):
    monkeypatch.delenv("RT_MAILER", raising=False)
    assert isinstance(get_mailer(), OutboxMailer)


def test_ses_from_env(ses_env):
    m = get_mailer()
    assert isinstance(m, SesMailer)
    assert (m.region, m.sender) == ("ap-south-1", SES_ENV["RT_MAIL_FROM"])
    assert m.url == "https://email.ap-south-1.amazonaws.com/v2/email/outbound-emails"


@pytest.mark.parametrize("missing", ["RT_MAIL_FROM", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"])
def test_ses_without_settings_fails_at_startup(ses_env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    from app.main import create_app

    with pytest.raises(RuntimeError, match=missing):
        create_app()


@pytest.mark.parametrize("mailer", [None, "outbox"])
def test_a_deployment_without_ses_fails_at_startup(monkeypatch, mailer):
    """RT_MAILER unset (the outbox default) on a real domain would write sign-in links to a file."""
    monkeypatch.setenv("RT_PUBLIC_URL", "https://app.example.com")
    if mailer:
        monkeypatch.setenv("RT_MAILER", mailer)
    else:
        monkeypatch.delenv("RT_MAILER", raising=False)
    from app.main import create_app

    with pytest.raises(RuntimeError, match="RT_MAILER=outbox is for localhost only"):
        create_app()


@pytest.mark.parametrize("url", ["http://localhost:3000", "http://127.0.0.1:3100"])
def test_the_outbox_works_on_localhost(monkeypatch, url):
    monkeypatch.setenv("RT_PUBLIC_URL", url)
    monkeypatch.delenv("RT_MAILER", raising=False)
    assert isinstance(get_mailer(), OutboxMailer)


def test_a_deployment_with_ses_starts(ses_env, monkeypatch):
    monkeypatch.setenv("RT_PUBLIC_URL", "https://app.example.com")
    from app.main import create_app

    create_app()


def test_unknown_mailer_fails_at_startup(monkeypatch):
    monkeypatch.setenv("RT_MAILER", "carrier-pigeon")
    from app.main import create_app

    with pytest.raises(RuntimeError, match="Unknown RT_MAILER"):
        create_app()


# --- outbox (dev and e2e read these files) ---------------------------------------------


def test_outbox_format_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(mailer, "OUTBOX", tmp_path / "outbox")
    OutboxMailer().send(a_mail())
    [f] = (tmp_path / "outbox").iterdir()
    assert f.read_text() == (
        f"To: {TO}\nSubject: Your sign-in link for Resume Tailor\n\n"
        "Open this link within 15 minutes, in the same browser:\n"
        f"http://localhost:3000/auth/email#token={TOKEN}\n"
    )


# --- SES -------------------------------------------------------------------------------


def test_sigv4_matches_aws_test_suite():
    """AWS SigV4 test suite, case get-vanilla."""
    headers = sigv4_headers(
        "GET", "https://example.amazonaws.com/", b"", {}, key_id="AKIDEXAMPLE",
        secret="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", region="us-east-1", service="service",
        now=datetime(2015, 8, 30, 12, 36, tzinfo=UTC),
    )
    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
        "SignedHeaders=host;x-amz-date, "
        "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    )


def test_ses_sends_text_and_html(ses_env, fake_ses):
    get_mailer().send(a_mail())
    [req] = fake_ses.calls
    assert req.method == "POST"
    assert str(req.url) == "https://email.ap-south-1.amazonaws.com/v2/email/outbound-emails"
    assert req.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDTEST/")
    assert "/ap-south-1/ses/aws4_request" in req.headers["authorization"]
    assert "x-amz-security-token" not in req.headers
    body = json.loads(req.content)
    assert body["FromEmailAddress"] == SES_ENV["RT_MAIL_FROM"]
    assert body["Destination"] == {"ToAddresses": [TO]}
    assert "ConfigurationSetName" not in body
    simple = body["Content"]["Simple"]
    assert simple["Subject"]["Data"] == "Your sign-in link for Resume Tailor"
    link = f"http://localhost:3000/auth/email#token={TOKEN}"
    assert link in simple["Body"]["Text"]["Data"]
    assert f'href="{link}"' in simple["Body"]["Html"]["Data"]


def test_ses_optional_settings(ses_env, fake_ses, monkeypatch):
    monkeypatch.setenv("RT_SES_REGION", "eu-west-1")
    monkeypatch.setenv("RT_SES_CONFIGURATION_SET", "magic-links")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "sess-tok")
    get_mailer().send(a_mail())
    [req] = fake_ses.calls
    assert req.url.host == "email.eu-west-1.amazonaws.com"
    assert req.headers["x-amz-security-token"] == "sess-tok"
    assert "x-amz-security-token" in req.headers["authorization"]  # signed, not just sent
    assert json.loads(req.content)["ConfigurationSetName"] == "magic-links"


def test_html_escapes_the_link():
    html = mailer.html_body(Mail(to=TO, subject="s", link='https://x/"><script>'))
    assert "<script>" not in html and "&quot;&gt;&lt;script&gt;" in html


@pytest.mark.parametrize("status", [400, 403, 429, 500])
def test_ses_error_keeps_only_the_status(ses_env, fake_ses, status):
    # SES sandbox errors name the unverified recipient; none of it may surface.
    fake_ses.response = httpx2.Response(status, json={"message": f"Email address is not verified: {TO}"})
    with pytest.raises(MailerError) as err:
        get_mailer().send(a_mail())
    assert err.value.reason == f"ses_{status}"
    assert TO not in str(err.value) and err.value.__cause__ is None and err.value.__context__ is None


def test_ses_network_error(ses_env):
    def boom(request):
        raise httpx2.ConnectError("unreachable", request=request)

    mailer.set_transport(httpx2.MockTransport(boom))
    try:
        with pytest.raises(MailerError, match="network"):
            get_mailer().send(a_mail())
    finally:
        mailer.set_transport(None)


# --- through the API -------------------------------------------------------------------


def test_failed_send_is_503_and_logs_no_address(client, fake_ses, caplog):
    fake_ses.response = httpx2.Response(400, json={"message": f"Email address is not verified: {TO}"})
    mailer.set_mailer(SesMailer(sender="no-reply@mail.example.com", region="ap-south-1",
                                key_id="AKIDTEST", secret="secret-test"))
    caplog.set_level(logging.DEBUG)
    csrf = {"X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]}
    res = client.post("/api/auth/email/start", json={"email": TO}, headers=csrf)
    assert (res.status_code, res.json()) == (503, {"detail": "email_unavailable"})
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "app.auth.events"]
    assert {"event": "magic_link_failed", "outcome": "error", "provider": "email", "reason": "ses_400"} in events
    assert TO not in caplog.text and TOKEN not in caplog.text and "#token=" not in caplog.text
