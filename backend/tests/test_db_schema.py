"""Schema guarantees from migration 0001_core_auth, checked against real Postgres."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Account,
    AuthSession,
    Base,
    ConsentNotice,
    ConsentRecord,
    EmailToken,
    Invite,
    InviteRedemption,
    PendingAuth,
    User,
)
from tests.conftest import alembic_config

NOW = datetime.now(UTC)


def make_user(db, email="ada@example.com", **kw) -> User:
    user = User(
        email=email,
        email_verified_at=NOW,
        activated_at=NOW,
        age_confirmed_at=NOW,
        terms_version="2026-11-v1",
        terms_accepted_at=NOW,
        **kw,
    )
    db.add(user)
    db.flush()
    return user


def make_notice(db, purpose="service", version="2026-11-v1") -> ConsentNotice:
    notice = ConsentNotice(
        purpose=purpose,
        version=version,
        body_sha256="0" * 64,
        body_url=f"/legal/notice/{purpose}/{version}",
        published_at=NOW,
    )
    db.add(notice)
    db.flush()
    return notice


def make_consent(db, user, notice, action="granted") -> ConsentRecord:
    record = ConsentRecord(
        user_id=user.id, subject_ref="hmac-of-email", notice_id=notice.id,
        purpose=notice.purpose, action=action, method="signup",
    )
    db.add(record)
    db.flush()
    return record


def rejects(db, *objects):
    """Flushing these objects violates a constraint; the test's transaction stays usable."""
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add_all(objects)
            db.flush()


# --- migration -----------------------------------------------------------------


def test_models_match_migration(pg_engine):
    with pg_engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(ctx, Base.metadata) == []


def test_migration_downgrades_and_upgrades_cleanly(pg_url):
    cfg = alembic_config(pg_url)
    command.downgrade(cfg, "base")
    engine = create_engine(pg_url)
    try:
        with engine.connect() as conn:
            left = conn.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
            )).scalar()
        assert left == 0
    finally:
        engine.dispose()
        command.upgrade(cfg, "head")


# --- users and accounts ----------------------------------------------------------


def test_user_email_must_be_lowercase(db):
    rejects(db, User(email="Ada@Example.com", email_verified_at=NOW, activated_at=NOW,
                     age_confirmed_at=NOW, terms_version="v1", terms_accepted_at=NOW))


def test_live_email_is_unique_but_reusable_after_deletion(db):
    first = make_user(db)
    rejects(db, User(email="ada@example.com", email_verified_at=NOW, activated_at=NOW,
                     age_confirmed_at=NOW, terms_version="v1", terms_accepted_at=NOW))
    first.deleted_at = NOW
    db.flush()
    make_user(db)  # same address, new live user


def test_user_cannot_exist_without_activation_and_consent(db):
    """No pre-invite or pre-consent user rows: these columns are NOT NULL."""
    rejects(db, User(email="bo@example.com", email_verified_at=NOW))


def test_user_can_have_several_accounts(db):
    user = make_user(db)
    db.add_all([
        Account(user_id=user.id, provider="google", provider_account_id="g-1", email_at_link=user.email),
        Account(user_id=user.id, provider="github", provider_account_id="42", email_at_link=user.email),
        Account(user_id=user.id, provider="email", provider_account_id=user.email, email_at_link=user.email),
    ])
    db.flush()
    assert len(db.scalars(select(Account).where(Account.user_id == user.id)).all()) == 3


def test_provider_identity_belongs_to_one_user(db):
    a, b = make_user(db), make_user(db, email="bo@example.com")
    db.add(Account(user_id=a.id, provider="github", provider_account_id="42", email_at_link=a.email))
    db.flush()
    rejects(db, Account(user_id=b.id, provider="github", provider_account_id="42", email_at_link=b.email))


def test_unknown_provider_rejected(db):
    user = make_user(db)
    rejects(db, Account(user_id=user.id, provider="twitter", provider_account_id="1", email_at_link=user.email))


def test_deleting_a_user_removes_accounts_sessions_and_redemptions(db):
    user = make_user(db)
    invite = Invite(code_hash="h1", code_hint="ABCD")
    db.add_all([
        Account(user_id=user.id, provider="google", provider_account_id="g-1", email_at_link=user.email),
        AuthSession(session_token_hash="s1", user_id=user.id, expires_at=NOW + timedelta(days=30)),
        invite,
    ])
    db.flush()
    db.add(InviteRedemption(invite_id=invite.id, user_id=user.id))
    db.flush()

    db.delete(user)
    db.flush()
    db.expunge_all()
    for model in (Account, AuthSession, InviteRedemption):
        assert db.scalars(select(model)).all() == []


# --- invites -----------------------------------------------------------------------


def test_invite_uses_cannot_exceed_max_uses(db):
    rejects(db, Invite(code_hash="h1", code_hint="ABCD", max_uses=1, uses=2))


def test_user_redeems_at_most_one_invite(db):
    user = make_user(db)
    i1, i2 = Invite(code_hash="h1", code_hint="AAAA"), Invite(code_hash="h2", code_hint="BBBB")
    db.add_all([i1, i2])
    db.flush()
    db.add(InviteRedemption(invite_id=i1.id, user_id=user.id))
    db.flush()
    rejects(db, InviteRedemption(invite_id=i2.id, user_id=user.id))


# --- pending sign-ups and magic-link tokens --------------------------------------------


def pending(**kw) -> PendingAuth:
    base = dict(token_hash=uuid.uuid4().hex, kind="signup", provider="github",
                provider_account_id="42", verified_email="ada@example.com",
                expires_at=NOW + timedelta(minutes=15))
    return PendingAuth(**(base | kw))


def test_signup_pending_identity_needs_a_verified_email(db):
    rejects(db, pending(verified_email=None))
    db.add(pending(kind="needs_email", verified_email=None))
    db.flush()


def test_invite_attaches_only_to_a_verified_signup(db):
    invite = Invite(code_hash="h1", code_hint="ABCD")
    db.add(invite)
    db.flush()
    rejects(db, pending(kind="needs_email", verified_email=None, invite_id=invite.id))
    db.add(pending(invite_id=invite.id))
    db.flush()


def test_email_token_purpose_matches_pending_link(db):
    p = pending(kind="needs_email", verified_email=None)
    db.add(p)
    db.flush()
    soon = NOW + timedelta(minutes=15)
    rejects(db, EmailToken(token_hash="t1", email="ada@example.com", purpose="verify_pending", expires_at=soon))
    rejects(db, EmailToken(token_hash="t2", email="ada@example.com", purpose="login",
                           pending_id=p.id, expires_at=soon))
    db.add(EmailToken(token_hash="t3", email="ada@example.com", purpose="verify_pending",
                      pending_id=p.id, expires_at=soon))
    db.flush()


# --- consent -------------------------------------------------------------------------


def test_consent_records_are_append_only(db):
    record = make_consent(db, make_user(db), make_notice(db))
    for statement in (
        "UPDATE consent_records SET action = 'withdrawn' WHERE id = :id",
        "DELETE FROM consent_records WHERE id = :id",
    ):
        with pytest.raises(IntegrityError, match="append-only"):
            with db.begin_nested():
                db.execute(text(statement), {"id": record.id})


def test_consent_survives_user_purge_without_user_id(db):
    user = make_user(db)
    record = make_consent(db, user, make_notice(db))
    db.delete(user)
    db.flush()
    row = db.execute(text("SELECT user_id, subject_ref FROM consent_records WHERE id = :id"),
                     {"id": record.id}).one()
    assert row.user_id is None and row.subject_ref == "hmac-of-email"


def test_current_consents_shows_the_latest_action(db):
    user = make_user(db)
    notice = make_notice(db, purpose="research")
    make_consent(db, user, notice, "granted")
    # created_at is now() for both (same transaction); id breaks the tie.
    make_consent(db, user, notice, "withdrawn")
    action = db.execute(text(
        "SELECT action FROM current_consents WHERE user_id = :u AND purpose = 'research'"
    ), {"u": user.id}).scalar_one()
    assert action == "withdrawn"
