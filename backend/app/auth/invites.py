"""Invite codes: generated once, stored as sha256 of the normalized code."""

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Invite

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I


def normalize(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def hash_code(code: str) -> str:
    return hashlib.sha256(normalize(code).encode()).hexdigest()


def generate_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return "-".join(raw[i:i + 4] for i in range(0, 12, 4))


def _usable(email: str):
    now = datetime.now(UTC)
    return (
        Invite.revoked_at.is_(None),
        or_(Invite.expires_at.is_(None), Invite.expires_at > now),
        Invite.uses < Invite.max_uses,
        or_(Invite.email.is_(None), Invite.email == email),
    )


async def find_usable(db: AsyncSession, code: str, email: str) -> uuid.UUID | None:
    """The invite this code names, if it can still be redeemed by `email`. Does not consume it."""
    if not normalize(code):
        return None
    return (await db.execute(
        select(Invite.id).where(Invite.code_hash == hash_code(code), *_usable(email))
    )).scalar_one_or_none()


async def find_bound(db: AsyncSession, email: str) -> uuid.UUID | None:
    """A usable invite issued to this exact verified email, so no code needs typing."""
    return (await db.execute(
        select(Invite.id)
        .where(Invite.email == email, *_usable(email))
        .order_by(Invite.created_at)
        .limit(1)
    )).scalar_one_or_none()
