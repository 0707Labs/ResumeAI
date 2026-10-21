"""Credit ledger and passes.

users.credits_balance is a cache of SUM(credit_transactions.delta), written only by
app.billing.ledger in the same transaction as the ledger row; neither can go below
zero. credit_transactions is append-only (same trigger pattern as consent_records).

Revision ID: 0003_credit_ledger
Revises: 0002_email_link_tokens
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003_credit_ledger"
down_revision: str | None = "0002_email_link_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASONS = (
    "reason IN ('signup_bonus', 'purchase', 'pass_grant', 'analysis_charge', 'refund',"
    " 'referral', 'admin_adjust', 'purchase_reversal')"
)


def upgrade() -> None:
    op.add_column("users", sa.Column("credits_balance", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_users_credits_balance", "users", "credits_balance >= 0")

    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reference_id", sa.Text()),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_credit_transactions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_credit_transactions_user_id_users", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_credit_transactions_idempotency_key"),
        sa.CheckConstraint(REASONS, name="ck_credit_transactions_reason"),
        sa.CheckConstraint(
            "delta <> 0 OR reason = 'purchase_reversal'", name="ck_credit_transactions_delta_nonzero"
        ),
        sa.CheckConstraint("balance_after >= 0", name="ck_credit_transactions_balance_after"),
    )
    op.create_index("ix_credit_transactions_user_created", "credit_transactions", ["user_id", "created_at"])
    op.create_index("ix_credit_transactions_reference_id", "credit_transactions", ["reference_id"])
    op.execute(
        """
        CREATE FUNCTION credit_transactions_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' AND OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
             AND (NEW.id, NEW.delta, NEW.reason, NEW.reference_id, NEW.idempotency_key,
                  NEW.balance_after, NEW.note, NEW.created_at)
                 IS NOT DISTINCT FROM
                 (OLD.id, OLD.delta, OLD.reason, OLD.reference_id, OLD.idempotency_key,
                  OLD.balance_after, OLD.note, OLD.created_at) THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'credit_transactions is append-only' USING ERRCODE = 'restrict_violation';
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER credit_transactions_append_only
        BEFORE UPDATE OR DELETE ON credit_transactions
        FOR EACH ROW EXECUTE FUNCTION credit_transactions_append_only();
        """
    )

    op.create_table(
        "passes",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("product_key", sa.Text(), nullable=False),
        sa.Column("reference_id", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analyses_cap", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_passes"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_passes_user_id_users", ondelete="SET NULL"),
        sa.UniqueConstraint("reference_id", name="uq_passes_reference_id"),
        sa.CheckConstraint("expires_at > starts_at", name="ck_passes_period"),
        sa.CheckConstraint("analyses_cap > 0", name="ck_passes_analyses_cap"),
    )
    op.create_index("ix_passes_user_expires", "passes", ["user_id", "expires_at"])


def downgrade() -> None:
    op.drop_table("passes")
    op.execute("DROP TRIGGER credit_transactions_append_only ON credit_transactions")
    op.execute("DROP FUNCTION credit_transactions_append_only()")
    op.drop_table("credit_transactions")
    op.drop_constraint("ck_users_credits_balance", "users", type_="check")
    op.drop_column("users", "credits_balance")
