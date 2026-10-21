"""Webhook idempotency, subscriptions, admin review flags, and payment amounts.

Revision ID: 0005_webhooks
Revises: 0004_payments
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0005_webhooks"
down_revision: str | None = "0004_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.func.now() if default else None)


def upgrade() -> None:
    for column in (
        sa.Column("provider_subscription_id", sa.Text()),
        sa.Column("currency", sa.Text()),
        sa.Column("amount_minor", sa.Integer()),
        sa.Column("tax_minor", sa.Integer()),
        sa.Column("settlement_amount_minor", sa.Integer()),
        sa.Column("settlement_currency", sa.Text()),
        _ts("paid_at"),
        sa.Column("credits_reversed", sa.Integer(), nullable=False, server_default="0"),
    ):
        op.add_column("payments", column)
    op.create_check_constraint("ck_payments_credits_reversed", "payments", "credits_reversed >= 0")

    op.create_table(
        "processed_webhook_events",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        _ts("occurred_at", nullable=False),
        _ts("received_at", nullable=False, default=True),
        _ts("processed_at"),
        sa.Column("outcome", sa.Text()),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.PrimaryKeyConstraint("provider", "event_id", name="pk_processed_webhook_events"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('processed', 'ignored', 'flagged')",
                           name="ck_processed_webhook_events_outcome"),
        sa.CheckConstraint("(processed_at IS NULL) = (outcome IS NULL)",
                           name="ck_processed_webhook_events_outcome_when_processed"),
    )
    op.create_index("ix_processed_webhook_events_failing", "processed_webhook_events", ["received_at"],
                    postgresql_where=sa.text("processed_at IS NULL"))

    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_subscription_id", sa.Text(), nullable=False),
        sa.Column("product_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _ts("current_period_end"),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _ts("last_event_at", nullable=False),
        _ts("created_at", nullable=False, default=True),
        _ts("updated_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_subscriptions"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_subscriptions_user_id_users",
                                ondelete="SET NULL"),
        sa.UniqueConstraint("provider", "provider_subscription_id",
                            name="uq_subscriptions_provider_provider_subscription_id"),
        sa.CheckConstraint("provider IN ('dodo')", name="ck_subscriptions_provider"),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'on_hold', 'paused', 'cancelled', 'failed', 'expired', 'past_due')",
            name="ck_subscriptions_status",
        ),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])

    op.create_table(
        "billing_reviews",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("payment_id", UUID(as_uuid=True)),
        sa.Column("detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        _ts("created_at", nullable=False, default=True),
        _ts("resolved_at"),
        sa.PrimaryKeyConstraint("id", name="pk_billing_reviews"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name="fk_billing_reviews_payment_id_payments",
                                ondelete="SET NULL"),
        sa.UniqueConstraint("dedupe_key", name="uq_billing_reviews_dedupe_key"),
        sa.CheckConstraint(
            "kind IN ('credits_already_used', 'partial_refund', 'dispute_opened', 'payment_mismatch',"
            " 'unknown_payment', 'user_missing')",
            name="ck_billing_reviews_kind",
        ),
    )
    op.create_index("ix_billing_reviews_payment_id", "billing_reviews", ["payment_id"])
    op.create_index("ix_billing_reviews_open", "billing_reviews", ["created_at"],
                    postgresql_where=sa.text("resolved_at IS NULL"))


def downgrade() -> None:
    op.drop_table("billing_reviews")
    op.drop_table("subscriptions")
    op.drop_table("processed_webhook_events")
    op.drop_constraint("ck_payments_credits_reversed", "payments", type_="check")
    for name in ("credits_reversed", "paid_at", "settlement_currency", "settlement_amount_minor", "tax_minor",
                 "amount_minor", "currency", "provider_subscription_id"):
        op.drop_column("payments", name)
