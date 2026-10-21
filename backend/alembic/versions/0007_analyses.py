"""Analyses: the unit of billing for the tailoring pipeline.

One row per resume + job run a signed-in user starts. It records what pays for the run
(an active pass, Pro, a credit, or the monthly free allowance) and, for a credit, the
reservation: the credit is charged when the run starts ('reserved'), kept when tailoring
succeeds with Claude ('committed') and given back once if it fails, falls back to rules
only, or is abandoned ('refunded'). Failed runs don't count against free or fair-use caps.

Also makes the ledger refuse a second charge or a second refund for one analysis.

Revision ID: 0007_analyses
Revises: 0006_llm_usage
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0007_analyses"
down_revision: str | None = "0006_llm_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("entitlement", sa.Text(), nullable=False),
        sa.Column("billing_state", sa.Text(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pass_id", UUID(as_uuid=True)),
        sa.Column("subscription_id", UUID(as_uuid=True)),
        sa.Column("usable_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("llm_degraded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_analyses"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_analyses_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pass_id"], ["passes.id"], name="fk_analyses_pass_id_passes"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"],
                                name="fk_analyses_subscription_id_subscriptions"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_analyses_user_id_idempotency_key"),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed')", name="ck_analyses_status"),
        sa.CheckConstraint("entitlement IN ('pass', 'pro', 'credit', 'free')", name="ck_analyses_entitlement"),
        sa.CheckConstraint("billing_state IN ('none', 'reserved', 'committed', 'refunded')",
                           name="ck_analyses_billing_state"),
        # Only a credit run has a reservation; it holds while pending and settles once.
        sa.CheckConstraint("(entitlement = 'credit') = (billing_state <> 'none')", name="ck_analyses_credit_state"),
        sa.CheckConstraint("(entitlement = 'credit') = (credits > 0)", name="ck_analyses_credits"),
        sa.CheckConstraint("(billing_state = 'reserved') = (entitlement = 'credit' AND status = 'pending')",
                           name="ck_analyses_reserved_while_pending"),
        sa.CheckConstraint("billing_state <> 'committed' OR status = 'succeeded'", name="ck_analyses_committed"),
        sa.CheckConstraint("(entitlement = 'pass') = (pass_id IS NOT NULL)", name="ck_analyses_pass"),
        sa.CheckConstraint("(entitlement = 'pro') = (subscription_id IS NOT NULL)", name="ck_analyses_pro"),
        sa.CheckConstraint("(status = 'pending') = (finished_at IS NULL)", name="ck_analyses_finished"),
    )
    op.create_index("ix_analyses_user_created", "analyses", ["user_id", "created_at"])
    op.create_index("ix_analyses_pass_id", "analyses", ["pass_id"], postgresql_where=sa.text("pass_id IS NOT NULL"))
    op.create_index("ix_analyses_subscription_id", "analyses", ["subscription_id"],
                    postgresql_where=sa.text("subscription_id IS NOT NULL"))
    op.create_index("ix_analyses_pending_until", "analyses", ["usable_until"],
                    postgresql_where=sa.text("status = 'pending'"))

    # Belt and braces on top of the charge:/refund: idempotency keys.
    op.create_index("ix_credit_transactions_one_charge", "credit_transactions", ["reference_id"], unique=True,
                    postgresql_where=sa.text("reason = 'analysis_charge'"))
    op.create_index("ix_credit_transactions_one_refund", "credit_transactions", ["reference_id"], unique=True,
                    postgresql_where=sa.text("reason = 'refund'"))


def downgrade() -> None:
    op.drop_index("ix_credit_transactions_one_refund", table_name="credit_transactions")
    op.drop_index("ix_credit_transactions_one_charge", table_name="credit_transactions")
    op.drop_table("analyses")
