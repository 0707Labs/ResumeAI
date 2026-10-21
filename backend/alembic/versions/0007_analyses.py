"""Analyses: one resume + job run per row, and the unit of billing.

Starting an analysis is free. It pins the parsed resume and job description on the
server, so the pipeline's Claude calls and the download are tied to those inputs
rather than to whatever a browser sends. Downloading the tailored resume is what
pays: the first DOCX/PDF export of an analysis is charged to an active pass, Pro, a
credit or the monthly free downloads (in that order). Re-exports of a paid analysis
are free. Charging and rendering happen in one transaction, so a failed export
charges nothing.

Also makes the ledger refuse a second charge or a second refund for one analysis.

Revision ID: 0007_analyses
Revises: 0006_llm_usage
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

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
        sa.Column("resume", JSONB(), nullable=False),
        sa.Column("jd", JSONB(), nullable=False),
        sa.Column("inputs_sha256", sa.Text(), nullable=False),
        sa.Column("tailored", JSONB()),
        sa.Column("llm_tailored", sa.Boolean()),
        sa.Column("tailored_at", sa.DateTime(timezone=True)),
        sa.Column("usable_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entitlement", sa.Text()),
        sa.Column("credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pass_id", UUID(as_uuid=True)),
        sa.Column("subscription_id", UUID(as_uuid=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_analyses"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_analyses_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pass_id"], ["passes.id"], name="fk_analyses_pass_id_passes"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"],
                                name="fk_analyses_subscription_id_subscriptions"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_analyses_user_id_idempotency_key"),
        sa.CheckConstraint("entitlement IS NULL OR entitlement IN ('pass', 'pro', 'credit', 'free')",
                           name="ck_analyses_entitlement"),
        # Paid exactly when an entitlement was charged for its first download.
        sa.CheckConstraint("(entitlement IS NULL) = (paid_at IS NULL)", name="ck_analyses_paid"),
        sa.CheckConstraint("(entitlement IS NOT DISTINCT FROM 'credit') = (credits > 0)", name="ck_analyses_credits"),
        sa.CheckConstraint("(entitlement IS NOT DISTINCT FROM 'pass') = (pass_id IS NOT NULL)", name="ck_analyses_pass"),
        sa.CheckConstraint("(entitlement IS NOT DISTINCT FROM 'pro') = (subscription_id IS NOT NULL)",
                           name="ck_analyses_pro"),
        sa.CheckConstraint("(tailored IS NULL) = (tailored_at IS NULL) AND (tailored IS NULL) = (llm_tailored IS NULL)",
                           name="ck_analyses_tailored"),
    )
    op.create_index("ix_analyses_user_created", "analyses", ["user_id", "created_at"])
    op.create_index("ix_analyses_user_paid", "analyses", ["user_id", "paid_at"],
                    postgresql_where=sa.text("paid_at IS NOT NULL"))
    op.create_index("ix_analyses_pass_id", "analyses", ["pass_id"], postgresql_where=sa.text("pass_id IS NOT NULL"))
    op.create_index("ix_analyses_subscription_id", "analyses", ["subscription_id"],
                    postgresql_where=sa.text("subscription_id IS NOT NULL"))

    # Belt and braces on top of the charge:/refund: idempotency keys.
    op.create_index("ix_credit_transactions_one_charge", "credit_transactions", ["reference_id"], unique=True,
                    postgresql_where=sa.text("reason = 'analysis_charge'"))
    op.create_index("ix_credit_transactions_one_refund", "credit_transactions", ["reference_id"], unique=True,
                    postgresql_where=sa.text("reason = 'refund'"))


def downgrade() -> None:
    op.drop_index("ix_credit_transactions_one_refund", table_name="credit_transactions")
    op.drop_index("ix_credit_transactions_one_charge", table_name="credit_transactions")
    op.drop_table("analyses")
