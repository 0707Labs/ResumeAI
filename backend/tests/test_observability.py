"""Sentry events never carry what users sent: resume and JD text, bodies, headers, cookies,
query strings, exception messages, log arguments or CLI arguments.

A secret marker goes into every place it could leak from; the captured events (from a
transport that keeps them in memory) must not contain it anywhere, while still saying where
the failure happened."""

import json
import logging
import sys

import pytest
import sentry_sdk
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sentry_sdk.transport import Transport

from app import observability
from app.main import create_app

# Built at runtime: events keep our own source lines around each frame, and the markers must
# only be able to reach an event through data, not through this file's text.
SECRET = "-".join(["Led", "SECRET", "7731", "migration", "of", "payroll"])  # a line of someone's resume
EMAIL = "@".join(["ada", "example.com"])
DSN = "https://public@o0.ingest.invalid/1"


def crash_and_report() -> None:
    try:
        raise RuntimeError(SECRET)
    except RuntimeError:
        sentry_sdk.capture_exception()


class Captured(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events: list[dict] = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.headers.get("type") in ("event", "transaction"):
                self.events.append(item.payload.json)


class Bullet(BaseModel):
    text: str
    metric: int


@pytest.fixture
def sentry(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", DSN)
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "1.0")
    transport = Captured()
    assert observability.init("api", transport=transport)
    yield transport
    observability.reset()


@pytest.fixture
def app(sentry):
    app = create_app()
    log = logging.getLogger("app.test")

    @app.post("/test/boom/{kind}")
    async def boom(kind: str, request: Request) -> None:
        body = await request.json()
        resume = body["resume"]["bullets"][0]
        if kind == "value":
            raise ValueError(f"could not parse bullet: {resume}")
        if kind == "pydantic":
            Bullet.model_validate({"text": resume, "metric": resume})
        log.error("tailoring failed for %s", resume)
        raise KeyError(resume)

    return app


def post(app, kind: str):
    client = TestClient(app, raise_server_exceptions=False)
    return client.post(
        f"/test/boom/{kind}?jd={SECRET}&token={SECRET}",
        json={"resume": {"bullets": [SECRET]}, "jd": {"text": SECRET}, "email": EMAIL},
        headers={"Authorization": f"Bearer {SECRET}", "X-CSRF-Token": SECRET, "User-Agent": SECRET,
                 "Cookie": f"__Host-rt_session={SECRET}; rt_csrf={SECRET}", "X-Forwarded-For": "203.0.113.9"},
    )


@pytest.mark.parametrize("kind,error", [("value", "ValueError"), ("pydantic", "ValidationError"), ("log", "KeyError")])
def test_events_say_where_not_what(app, sentry, kind, error):
    assert post(app, kind).status_code == 500
    sentry_sdk.flush()
    errors = [e for e in sentry.events if e.get("type") != "transaction"]
    assert errors, "the failure was reported"
    dumped = json.dumps(sentry.events)
    for leak in (SECRET, EMAIL, "203.0.113.9", "rt_session", "Bearer"):
        assert leak not in dumped

    event = next(e for e in errors if "exception" in e)
    assert event["request"] == {"method": "POST", "url": f"http://testserver/test/boom/{kind}"}
    assert event["exception"]["values"][-1]["type"] == error
    assert all("value" not in v for v in event["exception"]["values"])
    frames = event["exception"]["values"][-1]["stacktrace"]["frames"]
    assert any(f.get("function") == "boom" for f in frames) and all("vars" not in f for f in frames)
    assert event["tags"] == {"component": "api"} and "user" not in event and "breadcrumbs" not in event

    if kind == "log":
        [logged] = [e for e in errors if e.get("logentry")]
        assert logged["logentry"] == {"message": "tailoring failed for %s"}


def test_cli_arguments_are_not_sent(sentry, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app.auth.cli", "create-invite", "--email", EMAIL, "--note", SECRET])
    crash_and_report()
    sentry_sdk.flush()
    dumped = json.dumps(sentry.events)
    assert sentry.events and SECRET not in dumped and EMAIL not in dumped


def test_off_without_a_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert observability.init("api") is False
    assert not sentry_sdk.get_client().dsn  # no client, or the disabled one reset() leaves
