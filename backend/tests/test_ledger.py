"""Credit ledger and passes against real Postgres: idempotency, the never-negative
rule under concurrency, refund reversal policy, and the append-only trigger."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.billing import ledger
from app.billing.ledger import IdempotencyConflict, InsufficientCredits


@pytest.fixture
def sessions(pg_url, pg_engine):
    """Async sessions that really commit (concurrency needs separate connections).
    Billing and user tables are emptied afterwards."""
    engine = create_async_engine(pg_url, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE credit_transactions, passes, users CASCADE"))


def new_user(pg_engine) -> uuid.UUID:
    with pg_engine.begin() as conn:
        return conn.execute(text(
            "INSERT INTO users (email, email_verified_at, activated_at, age_confirmed_at,"
            " terms_version, terms_accepted_at) VALUES (:e, now(), now(), now(), 'v1', now()) RETURNING id"
        ), {"e": f"{uuid.uuid4().hex[:8]}@example.com"}).scalar_one()


@pytest.fixture
def uid(pg_engine) -> uuid.UUID:
    return new_user(pg_engine)


def run(coro):
    return asyncio.run(coro)


async def _in_txn(sessions, fn):
    async with sessions() as db, db.begin():
        return await fn(db)


def grant(sessions, uid, n, key, reason="purchase"):
    return run(_in_txn(sessions, lambda db: ledger.grant(db, uid, n, reason=reason, idempotency_key=key,
                                                          reference_id=key)))


def charge(sessions, uid, n, key):
    return run(_in_txn(sessions, lambda db: ledger.charge(db, uid, n, reason="analysis_charge",
                                                           idempotency_key=key, reference_id=key)))


def state(sessions, uid):
    async def read(db):
        return await ledger.balance(db, uid), await ledger.ledger_sum(db, uid)
    return run(_in_txn(sessions, read))


def test_grant_then_charge_updates_balance_and_ledger(sessions, uid):
    assert grant(sessions, uid, 5, "purchase:pay_1").balance == 5
    assert charge(sessions, uid, 1, "charge:a1").balance == 4
    assert state(sessions, uid) == (4, 4)


def test_same_key_applies_once(sessions, uid):
    first = grant(sessions, uid, 5, "purchase:pay_1")
    again = grant(sessions, uid, 5, "purchase:pay_1")
    assert first.applied and not again.applied
    assert again.transaction_id == first.transaction_id
    assert state(sessions, uid) == (5, 5)


def test_key_reused_for_another_user_or_reason_is_rejected(sessions, uid, pg_engine):
    other = new_user(pg_engine)
    grant(sessions, uid, 5, "purchase:pay_1")
    with pytest.raises(IdempotencyConflict):
        grant(sessions, other, 5, "purchase:pay_1")
    with pytest.raises(IdempotencyConflict):
        grant(sessions, uid, 5, "purchase:pay_1", reason="referral")


def test_charge_never_goes_negative(sessions, uid):
    grant(sessions, uid, 1, "purchase:pay_1")
    charge(sessions, uid, 1, "charge:a1")
    with pytest.raises(InsufficientCredits):
        charge(sessions, uid, 1, "charge:a2")
    assert state(sessions, uid) == (0, 0)


def test_concurrent_charges_never_overspend(sessions, uid):
    grant(sessions, uid, 3, "purchase:pay_1")

    async def one(i):
        try:
            async with sessions() as db, db.begin():
                await ledger.charge(db, uid, 1, reason="analysis_charge", idempotency_key=f"charge:{i}")
            return True
        except InsufficientCredits:
            return False

    async def race():
        return await asyncio.gather(*(one(i) for i in range(10)))

    results = run(race())
    assert results.count(True) == 3
    assert state(sessions, uid) == (0, 0)


def test_concurrent_grants_and_charges_stay_consistent(sessions, uid):
    async def g(i):
        async with sessions() as db, db.begin():
            await ledger.grant(db, uid, 1, reason="purchase", idempotency_key=f"g:{i}")

    async def c(i):
        try:
            async with sessions() as db, db.begin():
                await ledger.charge(db, uid, 1, reason="analysis_charge", idempotency_key=f"c:{i}")
        except InsufficientCredits:
            pass

    async def race():
        await asyncio.gather(*(f(i) for i in range(10) for f in (g, c)))

    run(race())
    balance, total = state(sessions, uid)
    assert balance == total >= 0


def test_concurrent_replays_of_one_grant_apply_once(sessions, uid):
    async def one():
        async with sessions() as db, db.begin():
            return await ledger.grant(db, uid, 5, reason="purchase", idempotency_key="purchase:pay_1")

    async def race():
        return await asyncio.gather(*(one() for _ in range(5)))

    results = run(race())
    assert sum(r.applied for r in results) == 1
    assert state(sessions, uid) == (5, 5)


def test_reversal_takes_back_unspent_credits_once(sessions, uid):
    grant(sessions, uid, 5, "purchase:pay_1")

    def reverse():
        return run(_in_txn(sessions, lambda db: ledger.reverse_purchase(
            db, uid, 5, idempotency_key="reversal:pay_1", reference_id="pay_1")))

    first, again = reverse(), reverse()
    assert (first.posted.delta, first.shortfall, first.posted.applied) == (-5, 0, True)
    assert (again.shortfall, again.posted.applied) == (0, False)
    assert state(sessions, uid) == (0, 0)


def test_reversal_after_credits_spent_floors_at_zero_and_reports_shortfall(sessions, uid):
    grant(sessions, uid, 5, "purchase:pay_1")
    for i in range(3):
        charge(sessions, uid, 1, f"charge:a{i}")
    result = run(_in_txn(sessions, lambda db: ledger.reverse_purchase(
        db, uid, 5, idempotency_key="reversal:pay_1", reference_id="pay_1")))
    assert (result.posted.delta, result.shortfall, result.posted.balance) == (-2, 3, 0)
    # Nothing left at all: the reversal is still recorded once, with delta 0.
    nothing_left = run(_in_txn(sessions, lambda db: ledger.reverse_purchase(
        db, uid, 1, idempotency_key="reversal:pay_2", reference_id="pay_2")))
    assert (nothing_left.posted.delta, nothing_left.shortfall) == (0, 1)
    assert state(sessions, uid) == (0, 0)


def test_ledger_rows_are_append_only(sessions, uid, pg_engine):
    grant(sessions, uid, 5, "purchase:pay_1")
    for stmt in ("UPDATE credit_transactions SET delta = 50", "DELETE FROM credit_transactions"):
        with pytest.raises(DBAPIError, match="append-only"):
            with pg_engine.begin() as conn:
                conn.execute(text(stmt))


def test_cached_balance_cannot_go_negative_even_bypassing_the_ledger(uid, pg_engine):
    with pytest.raises(DBAPIError):
        with pg_engine.begin() as conn:
            conn.execute(text("UPDATE users SET credits_balance = -1 WHERE id = :u"), {"u": uid})


# --- passes ----------------------------------------------------------------------------

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def grant_pass(sessions, uid, ref, now=NOW):
    return run(_in_txn(sessions, lambda db: ledger.grant_pass(
        db, uid, product_key="job_hunt_pass", days=30, analyses_cap=40, reference_id=ref, now=now)))


def test_pass_grant_is_idempotent(sessions, uid):
    first, again = grant_pass(sessions, uid, "pay_1"), grant_pass(sessions, uid, "pay_1")
    assert first.applied and not again.applied
    assert first.pass_id == again.pass_id
    assert first.expires_at - first.starts_at == timedelta(days=30)


def test_second_pass_starts_when_the_first_ends(sessions, uid):
    first = grant_pass(sessions, uid, "pay_1")
    second = grant_pass(sessions, uid, "pay_2", now=NOW + timedelta(days=10))
    assert second.starts_at == first.expires_at
    assert second.expires_at == first.expires_at + timedelta(days=30)


def test_revoked_pass_is_inactive_and_revokes_once(sessions, uid):
    grant_pass(sessions, uid, "pay_1")
    assert run(_in_txn(sessions, lambda db: ledger.revoke_pass(db, "pay_1", now=NOW))) is True
    assert run(_in_txn(sessions, lambda db: ledger.revoke_pass(db, "pay_1", now=NOW))) is False
    assert run(_in_txn(sessions, lambda db: ledger.active_passes(db, uid, now=NOW))) == []

