"""Sends magic links. Dev writes each email to backend/.dev-outbox/ (gitignored),
never to logs: the link is a credential. Production (SES in ap-south-1) is a later step."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from app.config import get_settings

OUTBOX = Path(__file__).resolve().parents[2] / ".dev-outbox"

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


class OutboxMailer:
    def send(self, mail: Mail) -> None:
        OUTBOX.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        (OUTBOX / f"{stamp}.txt").write_text(
            f"To: {mail.to}\nSubject: {mail.subject}\n\n"
            f"Open this link within 15 minutes, in the same browser:\n{mail.link}\n"
        )


_override: Mailer | None = None


def get_mailer() -> Mailer:
    if _override is not None:
        return _override
    kind = get_settings().mailer
    if kind == "outbox":
        return OutboxMailer()
    raise RuntimeError(f"Unknown RT_MAILER {kind!r}")


def set_mailer(mailer: Mailer | None) -> None:
    """Tests swap in a recording mailer."""
    global _override
    _override = mailer


def magic_link_mail(to: str, token: str, purpose: Purpose) -> Mail:
    # The token rides in the fragment: never sent to a server, logged or leaked via Referer.
    return Mail(to=to, subject=SUBJECTS[purpose], link=f"{get_settings().public_url}/auth/email#token={token}")
