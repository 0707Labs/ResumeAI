"""Admin bootstrap until the admin dashboard exists.

  .venv/bin/python -m app.auth.cli create-invite [--email a@b.c] [--max-uses N] [--days N] [--note TEXT]
  .venv/bin/python -m app.auth.cli publish-notice PURPOSE VERSION BODY_URL --body-file FILE
  ADMIN_BOOTSTRAP_EMAIL=you@example.com .venv/bin/python -m app.auth.cli bootstrap-admin [--force]
  .venv/bin/python -m app.auth.cli expire-invites   (daily: frees the slots of expired, unused invites)

The invite code is printed once; only its hash is stored."""

import argparse
import hashlib
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app import observability
from app.admin import audit
from app.auth.invites import generate_code, hash_code
from app.config import get_settings
from app.db.models import CONSENT_PURPOSES, ConsentNotice, Invite, User


class BootstrapError(Exception):
    pass


def bootstrap_admin(db: Session, email: str, *, force: bool = False) -> str:
    """Make the existing account with `email` a superadmin (audited as the system). Commits.
    The account must exist (invite + consent + verified email), so the role never goes to
    an address nobody has proven. Refuses while another superadmin exists, unless forced."""
    email = email.strip().lower()
    if not email:
        raise BootstrapError("ADMIN_BOOTSTRAP_EMAIL is not set")
    user = db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)).with_for_update())
    if user is None:
        raise BootstrapError("no account with that email: sign up first, then run this again")
    if user.role == "superadmin":
        return "already superadmin"
    others = db.scalar(select(func.count()).select_from(User).where(
        User.role == "superadmin", User.deleted_at.is_(None), User.id != user.id))
    if others and not force:
        raise BootstrapError("a superadmin already exists; promote from /admin/settings, or pass --force")
    before, user.role = user.role, "superadmin"
    audit.record(db, None, "roles.bootstrap", target_type="user", target_id=user.id,
                 before={"role": before}, after={"role": "superadmin", "forced": bool(others)})
    db.commit()
    return "promoted to superadmin"


def expire_invites(db: Session, now: datetime | None = None) -> int:
    """Revoke personal invites that expired unused, so each sender's slot comes back
    (revoke_user_invite returns a slot only when the invite was never redeemed). Commits.
    Returns how many were revoked."""
    now = now or datetime.now(UTC)
    stale = db.execute(select(Invite.id, Invite.created_by).where(
        Invite.kind == "personal", Invite.revoked_at.is_(None), Invite.uses == 0,
        Invite.expires_at.is_not(None), Invite.expires_at <= now)).all()
    done = 0
    for invite_id, user_id in stale:
        done += bool(db.scalar(text("SELECT revoke_user_invite(:u, :i)"), {"u": user_id, "i": invite_id}))
        db.commit()  # one at a time: each takes the sender's row lock briefly
    return done


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.auth.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("create-invite")
    inv.add_argument("--email", help="bind the invite to this verified email")
    inv.add_argument("--max-uses", type=int, default=1)
    inv.add_argument("--days", type=int, help="expires after N days")
    inv.add_argument("--note")
    notice = sub.add_parser("publish-notice")
    notice.add_argument("purpose", choices=CONSENT_PURPOSES)
    notice.add_argument("version")
    notice.add_argument("body_url")
    notice.add_argument("--body-file", type=Path, required=True, help="the exact rendered notice text")
    notice.add_argument("--language", default="en")
    boot = sub.add_parser("bootstrap-admin", help="promote ADMIN_BOOTSTRAP_EMAIL's account to superadmin")
    boot.add_argument("--force", action="store_true", help="even though a superadmin exists")
    sub.add_parser("expire-invites", help="revoke expired, unused personal invites so their slots come back")
    args = parser.parse_args(argv)
    observability.init("cron")  # scheduled jobs and staff commands report crashes too

    engine = create_engine(get_settings().database_url)
    with Session(engine) as db:
        if args.cmd == "bootstrap-admin":
            try:
                print(bootstrap_admin(db, os.environ.get("ADMIN_BOOTSTRAP_EMAIL", ""), force=args.force))
            except BootstrapError as exc:
                engine.dispose()
                sys.exit(f"bootstrap-admin: {exc}")
        elif args.cmd == "expire-invites":
            print(f"revoked {expire_invites(db)} expired invite(s)")
        elif args.cmd == "create-invite":
            code = generate_code()
            db.add(Invite(
                code_hash=hash_code(code), code_hint=code[-4:],
                email=args.email.strip().lower() if args.email else None,
                max_uses=args.max_uses, note=args.note,
                expires_at=datetime.now(UTC) + timedelta(days=args.days) if args.days else None,
            ))
            db.commit()
            print(code)
        else:
            db.add(ConsentNotice(
                purpose=args.purpose, version=args.version, language=args.language,
                body_sha256=hashlib.sha256(args.body_file.read_bytes()).hexdigest(),
                body_url=args.body_url, published_at=datetime.now(UTC),
            ))
            db.commit()
            print(f"published {args.purpose} {args.version} ({args.language})")
    engine.dispose()


if __name__ == "__main__":
    main()
