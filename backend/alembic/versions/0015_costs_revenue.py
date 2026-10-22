"""Costs and revenue: richer LLM usage, what started each analysis, daily aggregates,
budget alerts.

- llm_usage gains user_id (from the analysis), latency_ms, status (ok, refused, truncated,
  invalid, error, rate_limited) and error_code. Failed calls are recorded too, so wasted
  spend and error rates show.
- analyses.entitlement: what allowed the run (free, pass, pro, credit), for cost by plan
  and free-tier burn.
- daily_llm_costs and daily_revenue: per-day rollups written by
  `python -m app.billing.cli refresh-aggregates` (idempotent; recomputes recent days), so
  the admin dashboard reads small tables. aggregate_runs records when each last ran.
- budget_alerts: one row per period and threshold (50/80/100%) already alerted, so an
  alert goes out once.
None of these have an rt_app grant: they're staff-only.

Revision ID: 0015_costs_revenue
Revises: 0014_admin_console
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0015_costs_revenue"
down_revision: str | None = "0014_admin_console"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("ok", "refused", "truncated", "invalid", "error", "rate_limited")
ENTITLEMENTS = ("free", "pass", "pro", "credit")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column("llm_usage", sa.Column("user_id", UUID(as_uuid=True)))
    op.add_column("llm_usage", sa.Column("latency_ms", sa.Integer()))
    op.add_column("llm_usage", sa.Column("status", sa.Text(), server_default="ok", nullable=False))
    op.add_column("llm_usage", sa.Column("error_code", sa.Text()))
    op.create_foreign_key("fk_llm_usage_user_id_users", "llm_usage", "users", ["user_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_llm_usage_status", "llm_usage", _in("status", STATUSES))
    op.create_check_constraint("ck_llm_usage_error_code_len", "llm_usage", "error_code IS NULL OR length(error_code) <= 80")
    op.create_index("ix_llm_usage_user_created", "llm_usage", ["user_id", "created_at"],
                    postgresql_where=sa.text("user_id IS NOT NULL"))
    op.execute("UPDATE llm_usage u SET user_id = a.user_id FROM analyses a WHERE a.id = u.analysis_id")

    op.add_column("analyses", sa.Column("entitlement", sa.Text()))
    op.create_check_constraint("ck_analyses_entitlement", "analyses",
                               "entitlement IS NULL OR " + _in("entitlement", ENTITLEMENTS))

    op.create_table(
        "daily_llm_costs",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("entitlement", sa.Text(), nullable=False),  # free/pass/pro/credit, or 'none' (no analysis)
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("wasted_usd", sa.Numeric(14, 6), nullable=False),  # spent on calls whose answer wasn't usable
        sa.Column("unpriced_calls", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("day", "stage", "model", "entitlement", name="pk_daily_llm_costs"),
    )
    op.create_table(
        "daily_revenue",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("product_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("payments", sa.Integer(), nullable=False),
        sa.Column("gross_minor", sa.BigInteger(), nullable=False),  # in `currency`, tax included
        sa.Column("refunded_minor", sa.BigInteger(), nullable=False),
        sa.Column("disputes", sa.Integer(), nullable=False),
        sa.Column("settled_usd_cents", sa.BigInteger(), nullable=False),  # excluding tax
        sa.Column("refunded_usd_cents", sa.BigInteger(), nullable=False),
        sa.Column("fees_usd_cents", sa.BigInteger(), nullable=False),  # estimated (billing.toml [fees.dodo])
        sa.Column("unsettled", sa.Integer(), nullable=False),  # paid, but no USD settlement yet
        sa.PrimaryKeyConstraint("day", "product_key", "currency", name="pk_daily_revenue"),
    )
    op.create_table(
        "aggregate_runs",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("name", name="pk_aggregate_runs"),
    )
    op.create_table(
        "budget_alerts",
        sa.Column("period", sa.Text(), nullable=False),  # 'day:2026-10-22' or 'month:2026-10'
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("spend_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("budget_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("period", "threshold", name="pk_budget_alerts"),
        sa.CheckConstraint("threshold IN (50, 80, 100)", name="ck_budget_alerts_threshold"),
    )


def downgrade() -> None:
    for table in ("budget_alerts", "aggregate_runs", "daily_revenue", "daily_llm_costs"):
        op.drop_table(table)
    op.drop_constraint("ck_analyses_entitlement", "analyses", type_="check")
    op.drop_column("analyses", "entitlement")
    op.drop_index("ix_llm_usage_user_created", table_name="llm_usage")
    op.drop_constraint("ck_llm_usage_error_code_len", "llm_usage", type_="check")
    op.drop_constraint("ck_llm_usage_status", "llm_usage", type_="check")
    op.drop_constraint("fk_llm_usage_user_id_users", "llm_usage", type_="foreignkey")
    for column in ("error_code", "status", "latency_ms", "user_id"):
        op.drop_column("llm_usage", column)
