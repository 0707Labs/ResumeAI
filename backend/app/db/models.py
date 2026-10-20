"""ORM models for auth, invites, waitlist and consent.

The Alembic migrations own the schema (CHECKs, partial indexes, the consent
trigger are hand-written there); these models mirror it so the app can query.
tests/test_db_schema.py fails if the two drift apart.

No user row exists before activation: a new sign-in waits in pending_auth
until an invite is redeemed and the required consent is given, in one
transaction. Every token is stored only as a sha256 hash.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

PROVIDERS = ("google", "github", "email")
CONSENT_PURPOSES = ("service", "research", "age_18_plus", "waitlist")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(Text, nullable=False)
    email_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="user")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    age_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Cache of the latest 'service' grant in consent_records (the record of truth).
    terms_version: Mapped[str] = mapped_column(Text, nullable=False)
    terms_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lower"),
        CheckConstraint(_in("role", ("user", "admin")), name="role"),
        CheckConstraint(_in("status", ("active", "suspended")), name="status"),
        Index("users_email_live", "email", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("users_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
    )


class Account(Base):
    """One login method of a user. Matching is always on (provider, provider_account_id)."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    # Google `sub`, GitHub numeric id as text, or the lowercased address for 'email'.
    provider_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    # Verified email when the link was made; audit context, never used for matching.
    email_at_link: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id"),
        CheckConstraint(_in("provider", PROVIDERS), name="provider"),
        CheckConstraint("email_at_link = lower(email_at_link)", name="email_at_link_lower"),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    session_token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = _created_at()
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # sha256(normalized code)
    code_hint: Mapped[str] = mapped_column(Text, nullable=False)  # last 4 chars, for the admin list
    email: Mapped[str | None] = mapped_column(Text)  # set = invite bound to this verified email
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    uses: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    bonus_credits: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint("email IS NULL OR email = lower(email)", name="email_lower"),
        CheckConstraint("max_uses >= 1", name="max_uses"),
        CheckConstraint("uses >= 0 AND uses <= max_uses", name="uses"),
        CheckConstraint("bonus_credits IS NULL OR bonus_credits >= 0", name="bonus_credits"),
    )


class InviteRedemption(Base):
    __tablename__ = "invite_redemptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    invite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invites.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConsentNotice(Base):
    """The exact notice text a person saw. Immutable; one row per language."""

    __tablename__ = "consent_notices"

    id: Mapped[uuid.UUID] = _uuid_pk()
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    body_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    body_url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("purpose", "version", "language"),
        CheckConstraint(_in("purpose", CONSENT_PURPOSES), name="purpose"),
    )


class ConsentRecord(Base):
    """Append-only consent history. A database trigger rejects edits and deletes;
    the only update allowed is the FK nulling user_id when a user is purged."""

    __tablename__ = "consent_records"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    subject_ref: Mapped[str] = mapped_column(Text, nullable=False, index=True)  # HMAC(email)
    notice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consent_notices.id"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    ip_hmac: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(_in("purpose", CONSENT_PURPOSES), name="purpose"),
        CheckConstraint(_in("action", ("granted", "withdrawn")), name="action"),
        CheckConstraint(
            _in("method", ("signup", "account_settings", "reconsent", "admin", "deletion")),
            name="method",
        ),
        Index("ix_consent_records_user_purpose_created", "user_id", "purpose", "created_at"),
    )


class Waitlist(Base):
    __tablename__ = "waitlist"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="waiting")
    notice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consent_notices.id"), nullable=False
    )
    invite_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invites.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created_at()
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lower"),
        CheckConstraint("source IS NULL OR length(source) <= 100", name="source_len"),
        CheckConstraint(_in("status", ("waiting", "invited", "converted")), name="status"),
        Index("ix_waitlist_status_created", "status", "created_at"),
    )


class PendingAuth(Base):
    """A sign-in identity waiting for the invite and consent steps (15 minutes).

    The browser holds a signed cookie with the raw token; only its hash is here.
    Never treated as authenticated."""

    __tablename__ = "pending_auth"

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    verified_email: Mapped[str | None] = mapped_column(Text)
    invite_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invites.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(_in("kind", ("signup", "needs_email")), name="kind"),
        CheckConstraint(_in("provider", PROVIDERS), name="provider"),
        CheckConstraint(
            "verified_email IS NULL OR verified_email = lower(verified_email)", name="email_lower"
        ),
        # Only a 'needs_email' identity may lack a verified email, and only a
        # verified one may carry an invite.
        CheckConstraint("kind = 'needs_email' OR verified_email IS NOT NULL", name="signup_has_email"),
        CheckConstraint("invite_id IS NULL OR kind = 'signup'", name="invite_only_signup"),
    )


class EmailToken(Base):
    """Single-use magic-link token: sign-in, or verifying a pending identity's email."""

    __tablename__ = "email_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    pending_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pending_auth.id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lower"),
        CheckConstraint(_in("purpose", ("login", "verify_pending")), name="purpose"),
        CheckConstraint(
            "(purpose = 'verify_pending') = (pending_id IS NOT NULL)", name="pending_matches_purpose"
        ),
    )
