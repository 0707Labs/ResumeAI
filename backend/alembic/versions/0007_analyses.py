"""Analyses and downloads: tailoring is free to try, the clean download pays.

analyses: one resume + job run per row. Starting one pins the parsed resume and job
description on the server, so the pipeline's Claude calls and the download are tied to
those inputs rather than to whatever a browser sends. It spends nothing: the monthly free
tailorings allow it, or past those, an active pass, Pro or a credit balance.

downloads: one row per clean DOCX/PDF download, the download log. A download is charged
to a pass, Pro or credits ('pass', 'pro', 'credit'), or covered by a paid download of the
same analysis within the re-download window ('window'). Fair-use caps count paid
downloads. final_resume is what the short-lived signed link renders.

Also makes the ledger refuse a second charge or a second refund for one reference.

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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_analyses"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_analyses_user_id_users", ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_analyses_user_id_idempotency_key"),
        sa.CheckConstraint("(tailored IS NULL) = (tailored_at IS NULL) AND (tailored IS NULL) = (llm_tailored IS NULL)",
                           name="ck_analyses_tailored"),
    )
    op.create_index("ix_analyses_user_created", "analyses", ["user_id", "created_at"])

    op.create_table(
        "downloads",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("analysis_id", UUID(as_uuid=True), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("paid_with", sa.Text(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pass_id", UUID(as_uuid=True)),
        sa.Column("subscription_id", UUID(as_uuid=True)),
        sa.Column("final_resume", JSONB(), nullable=False),
        sa.Column("served_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_downloads"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_downloads_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], name="fk_downloads_analysis_id_analyses",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pass_id"], ["passes.id"], name="fk_downloads_pass_id_passes"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"],
                                name="fk_downloads_subscription_id_subscriptions"),
        sa.CheckConstraint("format IN ('docx', 'pdf')", name="ck_downloads_format"),
        sa.CheckConstraint("paid_with IN ('pass', 'pro', 'credit', 'window')", name="ck_downloads_paid_with"),
        sa.CheckConstraint("(paid_with = 'credit') = (credits > 0)", name="ck_downloads_credits"),
        sa.CheckConstraint("(paid_with = 'pass') = (pass_id IS NOT NULL)", name="ck_downloads_pass"),
        sa.CheckConstraint("(paid_with = 'pro') = (subscription_id IS NOT NULL)", name="ck_downloads_pro"),
    )
    op.create_index("ix_downloads_analysis_created", "downloads", ["analysis_id", "created_at"])
    op.create_index("ix_downloads_pass_id", "downloads", ["pass_id"], postgresql_where=sa.text("pass_id IS NOT NULL"))
    op.create_index("ix_downloads_subscription_id", "downloads", ["subscription_id"],
                    postgresql_where=sa.text("subscription_id IS NOT NULL"))

    # Belt and braces on top of the download:/refund: idempotency keys.
    op.create_index("ix_credit_transactions_one_charge", "credit_transactions", ["reference_id"], unique=True,
                    postgresql_where=sa.text("reason = 'analysis_charge'"))
    op.create_index("ix_credit_transactions_one_refund", "credit_transactions", ["reference_id"], unique=True,
                    postgresql_where=sa.text("reason = 'refund'"))


def downgrade() -> None:
    op.drop_index("ix_credit_transactions_one_refund", table_name="credit_transactions")
    op.drop_index("ix_credit_transactions_one_charge", table_name="credit_transactions")
    op.drop_table("downloads")
    op.drop_table("analyses")
