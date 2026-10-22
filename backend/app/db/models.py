"""ORM models for auth, invites, waitlist, consent, and the credit ledger and passes.

The Alembic migrations own the schema (CHECKs, partial indexes, the consent
trigger are hand-written there); these models mirror it so the app can query.
tests/test_db_schema.py fails if the two drift apart.

No user row exists before activation: a new sign-in waits in pending_auth
until an invite is redeemed and the required consent is given, in one
transaction. Every token is stored only as a sha256 hash.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Numeric,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

PROVIDERS = ("google", "github", "email")
PAYMENT_STATUSES = (
    "created", "checkout_failed", "pending", "paid", "failed", "cancelled",
    "partially_refunded", "refunded", "disputed",
)
LEDGER_REASONS = (
    "signup_bonus", "purchase", "pass_grant", "analysis_charge", "refund",
    "referral", "admin_adjust", "purchase_reversal",
)
CONSENT_PURPOSES = ("service", "research", "age_18_plus", "waitlist")
ROLES = ("user", "support", "admin", "superadmin")  # app.auth.roles maps them to capabilities


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
    # Cache of SUM(credit_transactions.delta); only app.billing.ledger writes it, in the
    # same transaction as the ledger row. Its row lock serializes a user's credit changes.
    credits_balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    referral_code: Mapped[str | None] = mapped_column(Text, unique=True)  # made on first use
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # first-login wizard done/skipped
    avatar_removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # no provider picture again
    phone: Mapped[str | None] = mapped_column(Text)  # optional, E.164

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lower"),
        CheckConstraint("credits_balance >= 0", name="credits_balance"),
        CheckConstraint(_in("role", ROLES), name="role"),
        CheckConstraint(_in("status", ("active", "suspended")), name="status"),
        CheckConstraint("phone IS NULL OR phone ~ '^\\+[1-9][0-9]{6,14}$'", name="phone"),
        Index("users_email_live", "email", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("users_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
        Index("ix_users_staff", "role", postgresql_where=text("role <> 'user'")),
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
    reauth_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # step-up for superadmin actions


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
    # Invite-only mode: a referral link stands in for the invite (checked again at sign-up).
    referral_invite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    picture_url: Mapped[str | None] = mapped_column(Text)  # the provider's picture, imported after sign-up
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
        CheckConstraint("picture_url IS NULL OR (picture_url LIKE 'https://%' AND length(picture_url) <= 1000)",
                        name="picture_url"),
    )


class EmailToken(Base):
    """Single-use magic-link token: sign-in, verifying a pending identity's email,
    or adding email sign-in to a signed-in user's account (bound to that user)."""

    __tablename__ = "email_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    pending_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pending_auth.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lower"),
        CheckConstraint(_in("purpose", ("login", "verify_pending", "link")), name="purpose"),
        CheckConstraint(
            "(purpose = 'verify_pending') = (pending_id IS NOT NULL)", name="pending_matches_purpose"
        ),
        CheckConstraint("(purpose = 'link') = (user_id IS NOT NULL)", name="user_matches_purpose"),
    )


class CreditTransaction(Base):
    """The credit ledger, append-only (a trigger rejects edits and deletes; the one
    update allowed is the FK nulling user_id when a user is purged).

    Every change to users.credits_balance writes one row here, in the same
    transaction, through app.billing.ledger. 'refund' is a failed analysis giving its
    credit back; 'purchase_reversal' takes credits back after a payment refund or a
    lost dispute, floored at the balance (delta may then be 0, never below)."""

    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reference_id: Mapped[str | None] = mapped_column(Text)  # payment id, analysis id, ...
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(_in("reason", LEDGER_REASONS), name="reason"),
        CheckConstraint("delta <> 0 OR reason = 'purchase_reversal'", name="delta_nonzero"),
        CheckConstraint("balance_after >= 0", name="balance_after"),
        Index("ix_credit_transactions_user_created", "user_id", "created_at"),
        Index("ix_credit_transactions_reference_id", "reference_id"),
        # One charge and at most one refund per analysis, on top of the idempotency keys.
        Index("ix_credit_transactions_one_charge", "reference_id", unique=True,
              postgresql_where=text("reason = 'analysis_charge'")),
        Index("ix_credit_transactions_one_refund", "reference_id", unique=True,
              postgresql_where=text("reason = 'refund'")),
    )


class Pass(Base):
    """A time-limited pass (e.g. the 30-day Job Hunt Pass). One row per purchase;
    buying again while one is active starts the new one when the last one ends.
    Length and cap are copied from the catalog at grant time."""

    __tablename__ = "passes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    product_key: Mapped[str] = mapped_column(Text, nullable=False)
    reference_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # payment id
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    analyses_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint("expires_at > starts_at", name="period"),
        CheckConstraint("analyses_cap > 0", name="analyses_cap"),
        Index("ix_passes_user_expires", "user_id", "expires_at"),
    )


class BillingCustomer(Base):
    """A user's customer id at a payment provider, learned from their first payment."""

    __tablename__ = "billing_customers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        UniqueConstraint("provider", "provider_customer_id"),
        CheckConstraint(_in("provider", ("dodo",)), name="provider"),
    )


class Payment(Base):
    """One purchase attempt, created before the provider's checkout. Its id goes into
    the return URL; webhooks find it by provider_checkout_id. `snapshot` keeps what
    was promised (credits, pass days, caps, displayed prices, catalog version) so later
    catalog edits never change a past purchase. Only verified webhooks move it to paid."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    product_key: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="created")
    provider_checkout_id: Mapped[str | None] = mapped_column(Text)
    checkout_url: Mapped[str | None] = mapped_column(Text)
    checkout_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_payment_id: Mapped[str | None] = mapped_column(Text)
    provider_subscription_id: Mapped[str | None] = mapped_column(Text)
    # As reported by the provider's verified webhook (total incl. tax; minor units).
    currency: Mapped[str | None] = mapped_column(Text)
    amount_minor: Mapped[int | None] = mapped_column(Integer)
    tax_minor: Mapped[int | None] = mapped_column(Integer)
    settlement_amount_minor: Mapped[int | None] = mapped_column(Integer)
    settlement_currency: Mapped[str | None] = mapped_column(Text)
    settlement_tax_minor: Mapped[int | None] = mapped_column(Integer)
    # Sum of succeeded refunds, in the payment's currency (for revenue net of refunds).
    refunded_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Provider refund ids already applied, so a refund redelivered under a new id applies once.
    refund_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Credits taken back so far by refunds and lost disputes (requested, incl. any shortfall).
    credits_reversed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("credits_reversed >= 0", name="credits_reversed"),
        CheckConstraint("refunded_amount_minor >= 0", name="refunded_amount_minor"),
        UniqueConstraint("user_id", "idempotency_key"),
        UniqueConstraint("provider", "provider_checkout_id"),
        UniqueConstraint("provider", "provider_payment_id"),
        CheckConstraint(_in("provider", ("dodo",)), name="provider"),
        CheckConstraint(_in("mode", ("test", "live")), name="mode"),
        CheckConstraint(_in("kind", ("credit_pack", "pass", "subscription")), name="kind"),
        CheckConstraint(_in("status", PAYMENT_STATUSES), name="status"),
        Index("ix_payments_user_created", "user_id", "created_at"),
    )


SUBSCRIPTION_STATUSES = ("pending", "active", "on_hold", "paused", "cancelled", "failed", "expired", "past_due")
REVIEW_KINDS = (
    "credits_already_used", "partial_refund", "dispute_opened", "payment_mismatch",
    "unknown_payment", "user_missing",
)


class ProcessedWebhookEvent(Base):
    """One row per webhook delivery id. processed_at is set in the same transaction as
    the event's effects, so a replay of a processed id does nothing. A delivery that
    failed leaves processed_at NULL with a failure count, and the provider retries it."""

    __tablename__ = "processed_webhook_events"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = _created_at()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("outcome IS NULL OR " + _in("outcome", ("processed", "ignored", "flagged")),
                        name="outcome"),
        CheckConstraint("(processed_at IS NULL) = (outcome IS NULL)", name="outcome_when_processed"),
        Index("ix_processed_webhook_events_failing", "received_at",
              postgresql_where=text("processed_at IS NULL")),
    )


class Subscription(Base):
    """A provider subscription (Pro), mirrored from webhooks. Events can arrive out of
    order, so an event older than last_event_at is ignored."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_subscription_id: Mapped[str] = mapped_column(Text, nullable=False)
    product_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_subscription_id"),
        CheckConstraint(_in("provider", ("dodo",)), name="provider"),
        CheckConstraint(_in("status", SUBSCRIPTION_STATUSES), name="status"),
    )


class BillingReview(Base):
    """Something a human must look at: credits already spent when a refund came in,
    a partial refund, an open dispute, a payment that doesn't match our record.
    dedupe_key makes each flag appear once however often its webhook is delivered."""

    __tablename__ = "billing_reviews"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL"), index=True
    )
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created_at()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(_in("kind", REVIEW_KINDS), name="kind"),
        Index("ix_billing_reviews_open", "created_at", postgresql_where=text("resolved_at IS NULL")),
    )


class LlmUsage(Base):
    """One row per Claude call: tokens and cost, for spend tracking and cost per analysis.
    analysis_id is the server-side analyses.id the call was billed to (set only after the
    X-Analysis-Id header is checked against the signed-in user). No FK, so recording a
    usage row can never fail on it. No prompt or output text is stored."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)  # the model that answered (fallbacks!)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))  # NULL: model not priced in billing.toml
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (Index("ix_llm_usage_created_at", "created_at"),)


DOWNLOAD_FORMATS = ("docx", "pdf")
PAID_WITH = ("pass", "pro", "credit", "window")


class Analysis(Base):
    """One resume + job run (see app.billing.analyses).

    Starting one pins the parsed resume and job description, so Claude calls and the
    download are tied to these inputs (inputs_sha256), not to whatever a browser sends.
    The monthly free tailorings count these rows, except runs that ended rules-only
    (llm_tailored false). tailored is the last tailoring result. Claude may be used until
    usable_until. Downloads, which are what pays, are rows in downloads. The retention
    purge (app.billing.retention) clears resume, jd and tailored and sets purged_at; the
    rest of the row stays."""

    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    resume: Mapped[dict | None] = mapped_column(JSONB)  # None once purged
    jd: Mapped[dict | None] = mapped_column(JSONB)
    inputs_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    tailored: Mapped[dict | None] = mapped_column(JSONB)
    llm_tailored: Mapped[bool | None] = mapped_column(Boolean)
    tailored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usable_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    # Metadata for lists and the dashboard (0011). mentor_tip is text, so the purge clears it.
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL"))
    job_title: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    ats_before: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    ats_after: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    mentor_tip: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # deleting purges at once

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        CheckConstraint("(tailored_at IS NULL) = (llm_tailored IS NULL) AND (tailored IS NULL OR tailored_at IS NOT NULL)"
                        " AND (purged_at IS NOT NULL OR (tailored IS NULL) = (tailored_at IS NULL))", name="tailored"),
        CheckConstraint("(purged_at IS NULL) = (resume IS NOT NULL) AND (purged_at IS NULL) = (jd IS NOT NULL)"
                        " AND (purged_at IS NULL OR tailored IS NULL) AND (purged_at IS NULL OR mentor_tip IS NULL)",
                        name="purged"),
        CheckConstraint("(ats_before IS NULL OR ats_before BETWEEN 0 AND 100)"
                        " AND (ats_after IS NULL OR ats_after BETWEEN 0 AND 100)", name="ats"),
        CheckConstraint("(job_title IS NULL OR length(job_title) <= 200) AND (company IS NULL OR length(company) <= 200)"
                        " AND (mentor_tip IS NULL OR length(mentor_tip) <= 1000)", name="meta_len"),
        CheckConstraint("deleted_at IS NULL OR purged_at IS NOT NULL", name="deleted"),
        Index("ix_analyses_user_created", "user_id", "created_at"),
        Index("ix_analyses_unpurged_created", "created_at", postgresql_where=text("purged_at IS NULL")),
        Index("ix_analyses_resume_id", "resume_id", postgresql_where=text("resume_id IS NOT NULL")),
    )


class Download(Base):
    """One clean-file download of an analysis: the download log, and what downloads are
    paid in. paid_with is what paid ('pass', 'pro', 'credit'), or 'window' when a paid
    download of the same analysis less than redownload_free_days ago covers it. A credit
    is spent through the ledger with key download:{id}. final_resume is what the signed
    link renders (approved, verified text only); nothing here is logged. The retention
    purge clears final_resume and sets purged_at once the re-download window has passed."""

    __tablename__ = "downloads"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(Text, nullable=False)
    paid_with: Mapped[str] = mapped_column(Text, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pass_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("passes.id"))
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("subscriptions.id"))
    final_resume: Mapped[dict | None] = mapped_column(JSONB)  # None once purged
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(_in("format", DOWNLOAD_FORMATS), name="format"),
        CheckConstraint(_in("paid_with", PAID_WITH), name="paid_with"),
        CheckConstraint("(paid_with = 'credit') = (credits > 0)", name="credits"),
        CheckConstraint("(paid_with = 'pass') = (pass_id IS NOT NULL)", name="pass"),
        CheckConstraint("(paid_with = 'pro') = (subscription_id IS NOT NULL)", name="pro"),
        CheckConstraint("(purged_at IS NULL) = (final_resume IS NOT NULL)", name="purged"),
        Index("ix_downloads_analysis_created", "analysis_id", "created_at"),
        Index("ix_downloads_unpurged_created", "created_at", postgresql_where=text("purged_at IS NULL")),
        Index("ix_downloads_pass_id", "pass_id", postgresql_where=text("pass_id IS NOT NULL")),
        Index("ix_downloads_subscription_id", "subscription_id", postgresql_where=text("subscription_id IS NOT NULL")),
    )


REFERRAL_STATUSES = ("pending", "rewarded", "rejected")


class Referral(Base):
    """A referred account (see app.billing.referrals). One per referee. Credits move only
    through the ledger (reason 'referral', reference_id = this id); reward_credits and
    invitee_credits record what was paid. ip_hmac is the sign-up network, keyed, so
    clusters can be spotted without storing addresses."""

    __tablename__ = "referrals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    referrer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    referee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    reason: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    used_as_invite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ip_hmac: Mapped[str | None] = mapped_column(Text)
    reward_credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    invitee_credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = _created_at()
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # referrer was notified

    __table_args__ = (
        CheckConstraint(_in("status", REFERRAL_STATUSES), name="status"),
        CheckConstraint("referrer_id <> referee_id", name="not_self"),
        CheckConstraint("status <> 'rewarded' OR rewarded_at IS NOT NULL", name="rewarded"),
        CheckConstraint("reversed_at IS NULL OR status = 'rejected'", name="reversed"),
        Index("ix_referrals_referrer_created", "referrer_id", "created_at"),
        Index("ix_referrals_review", "created_at", postgresql_where=text("needs_review")),
        Index("ix_referrals_ip", "ip_hmac", "created_at", postgresql_where=text("ip_hmac IS NOT NULL")),
    )


class AdminAuditLog(Base):
    """One row per staff mutation, written in the mutation's own transaction (app.admin.audit).
    Append-only by trigger; no foreign keys, so entries outlive what they describe.
    before/after are summaries (ids, amounts, flags), never resume or JD text or secrets."""

    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # NULL = system
    actor_role: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # "<area>.<verb>", e.g. "credits.adjust"
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ip_hmac: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(_in("actor_role", ("system", *ROLES)), name="actor_role"),
        CheckConstraint("action ~ '^[a-z_]+\\.[a-z_]+$'", name="action"),
        CheckConstraint("reason IS NULL OR length(reason) <= 500", name="reason_len"),
        CheckConstraint("user_agent IS NULL OR length(user_agent) <= 300", name="ua_len"),
        Index("ix_admin_audit_log_created_at", "created_at"),
        Index("ix_admin_audit_log_actor_created", "actor_id", "created_at"),
        Index("ix_admin_audit_log_target", "target_type", "target_id", "created_at"),
    )


class AppSetting(Base):
    """Runtime switches that override env/billing.toml defaults (app.admin.settings)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,63}$'", name="key"),)


SENIORITY_LEVELS = ("intern", "junior", "mid", "senior", "lead", "principal")
WORK_MODES = ("remote", "hybrid", "onsite")
EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "internship", "freelance")
RESUME_SOURCES = ("upload", "paste", "edit")


class JobPreferences(Base):
    """What the user is looking for (onboarding step 2, profile tab). One row per user."""

    __tablename__ = "job_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    target_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    seniority: Mapped[str | None] = mapped_column(Text)
    industries: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    locations: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    work_modes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    employment_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    notice_period_days: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("seniority IS NULL OR " + _in("seniority", SENIORITY_LEVELS), name="seniority"),
        CheckConstraint("work_modes <@ ARRAY[" + ", ".join(repr(v) for v in WORK_MODES) + "]::text[]",
                        name="work_modes"),
        CheckConstraint("employment_types <@ ARRAY[" + ", ".join(repr(v) for v in EMPLOYMENT_TYPES) + "]::text[]",
                        name="employment_types"),
        CheckConstraint("notice_period_days IS NULL OR notice_period_days BETWEEN 0 AND 365", name="notice_period"),
        CheckConstraint("text_list_ok(target_roles, 10, 80)", name="target_roles"),
        CheckConstraint("text_list_ok(industries, 10, 80)", name="industries"),
        CheckConstraint("text_list_ok(locations, 10, 80)", name="locations"),
    )


class SavedResume(Base):
    """A base resume the user keeps (not purged; the user deletes it). Content lives in versions."""

    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("length(title) BETWEEN 1 AND 120", name="title"),
        Index("ix_resumes_user_created", "user_id", "created_at"),
        Index("ix_resumes_one_default", "user_id", unique=True, postgresql_where=text("is_default")),
    )


class ResumeVersion(Base):
    """One version of a saved resume: the parsed Resume JSON, bullet ids included.
    Never updated (trigger); an edit or re-upload adds the next version."""

    __tablename__ = "resume_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        UniqueConstraint("resume_id", "version"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(_in("source", RESUME_SOURCES), name="source"),
        CheckConstraint("file_name IS NULL OR length(file_name) <= 200", name="file_name"),
    )


class UserAvatar(Base):
    """The user's picture, re-encoded by us (app.profile.avatars): WebP, at most 256 KB."""

    __tablename__ = "user_avatars"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("content_type = 'image/webp'", name="content_type"),
        CheckConstraint("octet_length(data) BETWEEN 1 AND 262144", name="size"),
        CheckConstraint(_in("source", ("provider", "upload")), name="source"),
    )
