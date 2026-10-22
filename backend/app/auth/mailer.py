"""Sends magic links. RT_MAILER picks the transport:

- "outbox" (dev, tests, e2e): writes each email to backend/.dev-outbox/ (gitignored).
- "ses": Amazon SES v2 over HTTPS, signed with SigV4. See docs/email.md.

Never log or raise with the address, token or link: the link is a credential. SES error
bodies can echo the recipient, so they are dropped and only the status code is kept."""

import hashlib
import hmac
import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx2

from app.config import get_settings

OUTBOX = Path(__file__).resolve().parents[2] / ".dev-outbox"
HTTP_TIMEOUT = 10.0

Purpose = Literal["login", "verify_pending", "link"]

SUBJECTS = {
    "login": "Your sign-in link for Resume Tailor",
    "verify_pending": "Confirm your email for Resume Tailor",
    "link": "Add email sign-in to your Resume Tailor account",
}


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    link: str


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...


class MailerError(Exception):
    """Delivery failed. `reason` is a short code safe to log (e.g. "ses_400", "network")."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def text_body(mail: Mail) -> str:
    return f"Open this link within 15 minutes, in the same browser:\n{mail.link}\n"


def html_body(mail: Mail) -> str:
    link = html.escape(mail.link, quote=True)
    muted = 'style="font-size:13px;color:#52606d"'
    return (
        '<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        'color:#1f2933;line-height:1.5">'
        "<p>Open this link within 15 minutes, in the same browser:</p>"
        f'<p><a href="{link}" style="display:inline-block;padding:10px 18px;background:#1f2933;'
        'color:#ffffff;text-decoration:none;border-radius:6px">Continue to Resume Tailor</a></p>'
        f"<p {muted}>Or paste this into your browser:<br>{link}</p>"
        f"<p {muted}>Didn't ask for this? You can ignore this email.</p>"
        "</body></html>"
    )


class OutboxMailer:
    def send(self, mail: Mail) -> None:
        OUTBOX.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        (OUTBOX / f"{stamp}.txt").write_text(f"To: {mail.to}\nSubject: {mail.subject}\n\n{text_body(mail)}")


# --- Amazon SES ------------------------------------------------------------------------------

_transport: httpx2.BaseTransport | None = None  # tests inject a mock; None = real network


def set_transport(transport: httpx2.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def sigv4_headers(method: str, url: str, body: bytes, headers: dict[str, str], *, key_id: str, secret: str,
                  region: str, service: str, now: datetime) -> dict[str, str]:
    """AWS Signature Version 4 for a request with no query string. Returns `headers` plus
    host, x-amz-date and authorization; every header passed in is signed."""
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = amz_date[:8]
    parts = urlsplit(url)
    signed = {k.lower(): v.strip() for k, v in headers.items()} | {"host": parts.netloc, "x-amz-date": amz_date}
    names = sorted(signed)
    canonical = "\n".join([
        method, parts.path or "/", "",
        "".join(f"{k}:{signed[k]}\n" for k in names),
        ";".join(names), hashlib.sha256(body).hexdigest(),
    ])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = f"AWS4{secret}".encode()
    for part in (day, region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return signed | {
        "authorization": f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, "
                         f"SignedHeaders={';'.join(names)}, Signature={signature}",
    }


@dataclass(frozen=True)
class SesMailer:
    sender: str
    region: str
    key_id: str
    secret: str
    session_token: str = ""
    configuration_set: str = ""

    @property
    def url(self) -> str:
        return f"https://email.{self.region}.amazonaws.com/v2/email/outbound-emails"

    def payload(self, mail: Mail) -> dict:
        body: dict = {
            "FromEmailAddress": self.sender,
            "Destination": {"ToAddresses": [mail.to]},
            "Content": {"Simple": {
                "Subject": {"Data": mail.subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body(mail), "Charset": "UTF-8"},
                    "Html": {"Data": html_body(mail), "Charset": "UTF-8"},
                },
            }},
        }
        if self.configuration_set:
            body["ConfigurationSetName"] = self.configuration_set
        return body

    def send(self, mail: Mail) -> None:
        data = json.dumps(self.payload(mail)).encode()
        headers = {"content-type": "application/json"}
        if self.session_token:
            headers["x-amz-security-token"] = self.session_token
        headers = sigv4_headers("POST", self.url, data, headers, key_id=self.key_id, secret=self.secret,
                                region=self.region, service="ses", now=datetime.now(UTC))
        try:
            with httpx2.Client(timeout=HTTP_TIMEOUT, transport=_transport) as http:
                res = http.post(self.url, content=data, headers=headers)
        except httpx2.HTTPError:
            raise MailerError("network") from None
        if res.status_code != 200:
            raise MailerError(f"ses_{res.status_code}")


def _ses_from_settings() -> SesMailer:
    s = get_settings()
    missing = [name for name, value in (
        ("RT_MAIL_FROM", s.mail_from), ("AWS_ACCESS_KEY_ID", s.aws_access_key_id),
        ("AWS_SECRET_ACCESS_KEY", s.aws_secret_access_key),
    ) if not value]
    if missing:
        raise RuntimeError(f"RT_MAILER=ses needs {', '.join(missing)} (see docs/email.md)")
    return SesMailer(sender=s.mail_from, region=s.ses_region, key_id=s.aws_access_key_id,
                     secret=s.aws_secret_access_key, session_token=s.aws_session_token,
                     configuration_set=s.ses_configuration_set)


_override: Mailer | None = None


def get_mailer() -> Mailer:
    """Raises RuntimeError for an unknown RT_MAILER or a provider missing its settings.
    create_app calls this once so a misconfigured server fails at startup."""
    if _override is not None:
        return _override
    kind = get_settings().mailer
    if kind == "outbox":
        return OutboxMailer()
    if kind == "ses":
        return _ses_from_settings()
    raise RuntimeError(f"Unknown RT_MAILER {kind!r} (expected outbox or ses)")


def set_mailer(mailer: Mailer | None) -> None:
    """Tests swap in a recording mailer."""
    global _override
    _override = mailer


def magic_link_mail(to: str, token: str, purpose: Purpose) -> Mail:
    # The token rides in the fragment: never sent to a server, logged or leaked via Referer.
    return Mail(to=to, subject=SUBJECTS[purpose], link=f"{get_settings().public_url}/auth/email#token={token}")
