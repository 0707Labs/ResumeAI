"""Payments (one row per purchase attempt) and provider customer ids.

Revision ID: 0004_payments
Revises: 0003_credit_ledger
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0004_payments"
down_revision: str | None = "0003_credit_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = (
    "status IN ('created', 'checkout_failed', 'pending', 'paid', 'failed', 'cancelled',"
    " 'partially_refunded', 'refunded', 'disputed')"
)


def _ts(name: str, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.func.now() if default else None)


def upgrade() -> None:
    op.create_table(
        "billing_customers",
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_customer_id", sa.Text(), nullable=False),
        _ts("created_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("user_id", "provider", name="pk_billing_customers"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_billing_customers_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "provider", "provider_customer_id", name="uq_billing_customers_provider_provider_customer_id"
        ),
        sa.CheckConstraint("provider IN ('dodo')", name="ck_billing_customers_provider"),
    )

    op.create_table(
        "payments",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("product_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="created"),
        sa.Column("provider_checkout_id", sa.Text()),
        sa.Column("checkout_url", sa.Text()),
        _ts("checkout_expires_at"),
        sa.Column("provider_payment_id", sa.Text()),
        _ts("created_at", nullable=False, default=True),
        _ts("updated_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_payments_user_id_users", ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_payments_user_id_idempotency_key"),
        sa.UniqueConstraint("provider", "provider_checkout_id", name="uq_payments_provider_provider_checkout_id"),
        sa.UniqueConstraint("provider", "provider_payment_id", name="uq_payments_provider_provider_payment_id"),
        sa.CheckConstraint("provider IN ('dodo')", name="ck_payments_provider"),
        sa.CheckConstraint("mode IN ('test', 'live')", name="ck_payments_mode"),
        sa.CheckConstraint("kind IN ('credit_pack', 'pass', 'subscription')", name="ck_payments_kind"),
        sa.CheckConstraint(STATUSES, name="ck_payments_status"),
    )
    op.create_index("ix_payments_user_created", "payments", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("billing_customers")
