"""Admin bootstrap until the admin dashboard exists.

  .venv/bin/python -m app.auth.cli create-invite [--email a@b.c] [--max-uses N] [--days N] [--note TEXT]
  .venv/bin/python -m app.auth.cli publish-notice PURPOSE VERSION BODY_URL --body-file FILE

The invite code is printed once; only its hash is stored."""

import argparse
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth.invites import generate_code, hash_code
from app.config import get_settings
from app.db.models import CONSENT_PURPOSES, ConsentNotice, Invite


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
    args = parser.parse_args(argv)

    engine = create_engine(get_settings().database_url)
    with Session(engine) as db:
        if args.cmd == "create-invite":
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
