"""The only writer of credit_transactions, users.credits_balance and passes.

Every function runs inside the caller's transaction and never commits. Each one
first locks the user's row (SELECT ... FOR UPDATE), so a user's credit changes are
serialized: concurrent grants and charges can't race, and the balance never goes
below zero (a CHECK on both tables backs this up).

Each change carries an idempotency key. Repeating a key returns the original result
without changing anything, so a replayed webhook or a retried request is harmless.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CreditTransaction, Pass, User


class LedgerError(Exception):
    pass


class InsufficientCredits(LedgerError):
    pass


class IdempotencyConflict(LedgerError):
    """The key was already used for a different user or a different kind of change."""


@dataclass(frozen=True)
class Posted:
    transaction_id: int
    delta: int
    balance: int
    applied: bool  # False when this key had been posted before (a replay)


@dataclass(frozen=True)
class Reversal:
    posted: Posted
    requested: int
    shortfall: int  # credits already spent that could not be taken back; needs admin review


async def _lock_balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    balance = await db.scalar(select(User.credits_balance).where(User.id == user_id).with_for_update())
    if balance is None:
        raise LedgerError("unknown user")
    return balance


lock_user = _lock_balance  # for callers that must serialize with ledger writes for a user


async def _existing(db: AsyncSession, user_id: uuid.UUID, key: str, reason: str) -> Posted | None:
    row = await db.scalar(select(CreditTransaction).where(CreditTransaction.idempotency_key == key))
    if row is None:
        return None
    if row.user_id != user_id or row.reason != reason:
        raise IdempotencyConflict(key)
    return Posted(row.id, row.delta, row.balance_after, applied=False)


async def _write(db: AsyncSession, user_id: uuid.UUID, delta: int, balance: int, reason: str,
                 key: str, reference_id: str | None, note: str | None) -> Posted:
    after = balance + delta
    row = CreditTransaction(user_id=user_id, delta=delta, reason=reason, reference_id=reference_id,
                            idempotency_key=key, balance_after=after, note=note)
    db.add(row)
    await db.flush()
    await db.execute(update(User).where(User.id == user_id).values(credits_balance=after))
    return Posted(row.id, delta, after, applied=True)


async def post(db: AsyncSession, user_id: uuid.UUID, delta: int, *, reason: str, idempotency_key: str,
               reference_id: str | None = None, note: str | None = None) -> Posted:
    """Add (delta > 0) or spend (delta < 0) credits. Raises InsufficientCredits rather
    than letting the balance go negative."""
    if delta == 0:
        raise ValueError("delta must be non-zero")
    balance = await _lock_balance(db, user_id)
    if (done := await _existing(db, user_id, idempotency_key, reason)) is not None:
        return done
    if balance + delta < 0:
        raise InsufficientCredits(f"balance {balance}, needs {-delta}")
    return await _write(db, user_id, delta, balance, reason, idempotency_key, reference_id, note)


async def grant(db: AsyncSession, user_id: uuid.UUID, credits: int, *, reason: str, idempotency_key: str,
                reference_id: str | None = None, note: str | None = None) -> Posted:
    if credits <= 0:
        raise ValueError("a grant must be positive")
    return await post(db, user_id, credits, reason=reason, idempotency_key=idempotency_key,
                      reference_id=reference_id, note=note)


async def charge(db: AsyncSession, user_id: uuid.UUID, credits: int, *, reason: str, idempotency_key: str,
                 reference_id: str | None = None, note: str | None = None) -> Posted:
    if credits <= 0:
        raise ValueError("a charge must be positive")
    return await post(db, user_id, -credits, reason=reason, idempotency_key=idempotency_key,
                      reference_id=reference_id, note=note)


async def take_back(db: AsyncSession, user_id: uuid.UUID, credits: int, *, reason: str, idempotency_key: str,
                    reference_id: str, note: str | None = None) -> Reversal:
    """Take back credits granted earlier (a refunded purchase, a reversed referral), at
    most once per key.

    Policy: never below zero. If some credits were already spent, take back what is
    left and report the shortfall; the caller flags it for admin review. The row is
    written even when nothing can be taken back (delta 0), so it's recorded exactly once."""
    if credits <= 0:
        raise ValueError("a reversal must be positive")
    balance = await _lock_balance(db, user_id)
    if (done := await _existing(db, user_id, idempotency_key, reason)) is not None:
        return Reversal(done, credits, credits + done.delta)
    taken = min(credits, balance)
    shortfall = credits - taken
    if shortfall:
        note = f"{note + '; ' if note else ''}shortfall {shortfall} of {credits} credits"
    posted = await _write(db, user_id, -taken, balance, reason, idempotency_key, reference_id, note)
    return Reversal(posted, credits, shortfall)


async def reverse_purchase(db: AsyncSession, user_id: uuid.UUID, credits: int, *, idempotency_key: str,
                           reference_id: str, note: str | None = None) -> Reversal:
    """Take back a purchase's credits after a refund or a lost dispute (see take_back)."""
    return await take_back(db, user_id, credits, reason="purchase_reversal", idempotency_key=idempotency_key,
                           reference_id=reference_id, note=note)


async def balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    value = await db.scalar(select(User.credits_balance).where(User.id == user_id))
    if value is None:
        raise LedgerError("unknown user")
    return value


async def ledger_sum(db: AsyncSession, user_id: uuid.UUID) -> int:
    """SUM(delta): what the cached balance must equal (for reconciliation)."""
    total = await db.scalar(
        select(func.coalesce(func.sum(CreditTransaction.delta), 0)).where(CreditTransaction.user_id == user_id)
    )
    return int(total)


# --- passes --------------------------------------------------------------------------


@dataclass(frozen=True)
class PassGrant:
    pass_id: uuid.UUID
    starts_at: datetime
    expires_at: datetime
    applied: bool


async def grant_pass(db: AsyncSession, user_id: uuid.UUID, *, product_key: str, days: int, analyses_cap: int,
                     reference_id: str, now: datetime | None = None) -> PassGrant:
    """Grant a pass for a payment, once per reference_id. If the user already has
    an unexpired pass, the new one starts when the latest one ends."""
    now = now or datetime.now(UTC)
    await _lock_balance(db, user_id)
    existing = await db.scalar(select(Pass).where(Pass.reference_id == reference_id))
    if existing is not None:
        if existing.user_id != user_id:
            raise IdempotencyConflict(reference_id)
        return PassGrant(existing.id, existing.starts_at, existing.expires_at, applied=False)
    latest_end = await db.scalar(
        select(func.max(Pass.expires_at)).where(
            Pass.user_id == user_id, Pass.revoked_at.is_(None), Pass.expires_at > now
        )
    )
    starts = max(now, latest_end) if latest_end else now
    row = Pass(user_id=user_id, product_key=product_key, reference_id=reference_id, starts_at=starts,
               expires_at=starts + timedelta(days=days), analyses_cap=analyses_cap)
    db.add(row)
    await db.flush()
    return PassGrant(row.id, row.starts_at, row.expires_at, applied=True)


async def revoke_pass(db: AsyncSession, reference_id: str, *, now: datetime | None = None) -> bool:
    """Revoke the pass bought with this payment. True only the first time."""
    result = await db.execute(
        update(Pass).where(Pass.reference_id == reference_id, Pass.revoked_at.is_(None))
        .values(revoked_at=now or datetime.now(UTC))
    )
    return result.rowcount == 1


async def active_passes(db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None) -> list[Pass]:
    """Passes not revoked and not yet expired (including ones queued to start later)."""
    now = now or datetime.now(UTC)
    rows = await db.scalars(
        select(Pass).where(Pass.user_id == user_id, Pass.revoked_at.is_(None), Pass.expires_at > now)
        .order_by(Pass.starts_at)
    )
    return list(rows)
