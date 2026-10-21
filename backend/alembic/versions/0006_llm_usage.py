"""LLM usage and cost per call; settlement tax and refunded amount on payments.

Revision ID: 0006_llm_usage
Revises: 0005_webhooks
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0006_llm_usage"
down_revision: str | None = "0005_webhooks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("settlement_tax_minor", sa.Integer()))
    op.add_column("payments", sa.Column("refunded_amount_minor", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("payments", sa.Column("refund_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint("ck_payments_refunded_amount_minor", "payments", "refunded_amount_minor >= 0")

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("analysis_id", UUID(as_uuid=True)),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_llm_usage"),
    )
    op.create_index("ix_llm_usage_analysis_id", "llm_usage", ["analysis_id"])
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])


def downgrade() -> None:
    op.drop_table("llm_usage")
    op.drop_constraint("ck_payments_refunded_amount_minor", "payments", type_="check")
    op.drop_column("payments", "refund_ids")
    op.drop_column("payments", "refunded_amount_minor")
    op.drop_column("payments", "settlement_tax_minor")
