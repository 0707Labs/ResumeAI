"""Admin operations: quality counters, integration health, webhook replay.

- analyses gains verifier counts (metadata only, kept after the purge): bullets the
  tailoring produced, rewrites the verifier blocked, bullets with a warning; and at
  download, bullets approved and rejected and warnings the user approved anyway.
- daily_counters: plain per-day counts (resume parse failures and warnings by code,
  landing page views). No user, no IP, no content.
- integration_checks: the last health check per integration (status, sanitized error
  code, when it last passed).
- processed_webhook_events.payload: the verified event data, kept only while a delivery
  is failing so staff can replay it; cleared once it's processed.
None of these have an rt_app grant except the analyses columns (the table's grant covers them).

Revision ID: 0016_admin_ops
Revises: 0015_costs_revenue
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0016_admin_ops"
down_revision: str | None = "0015_costs_revenue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COUNTS = ("bullets_generated", "bullets_blocked", "bullets_flagged", "bullets_approved", "bullets_rejected",
          "flag_overrides")
STATUSES = ("healthy", "degraded", "failing", "not_configured")


def upgrade() -> None:
    for column in COUNTS:
        op.add_column("analyses", sa.Column(column, sa.Integer()))
    op.create_check_constraint("ck_analyses_quality_counts", "analyses",
                               " AND ".join(f"({c} IS NULL OR {c} >= 0)" for c in COUNTS))

    op.create_table(
        "daily_counters",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("day", "name", name="pk_daily_counters"),
        sa.CheckConstraint("name ~ '^[a-z][a-z0-9_.:]{0,79}$'", name="ck_daily_counters_name"),
    )
    op.create_table(
        "integration_checks",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_ok_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("checked_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.PrimaryKeyConstraint("name", name="pk_integration_checks"),
        sa.CheckConstraint("status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")",
                           name="ck_integration_checks_status"),
        sa.CheckConstraint("error_code IS NULL OR length(error_code) <= 120", name="ck_integration_checks_error_len"),
    )
    op.add_column("processed_webhook_events", sa.Column("payload", JSONB()))
    op.create_check_constraint("ck_processed_webhook_events_payload_while_failing", "processed_webhook_events",
                               "payload IS NULL OR processed_at IS NULL")


def downgrade() -> None:
    op.drop_constraint("ck_processed_webhook_events_payload_while_failing", "processed_webhook_events", type_="check")
    op.drop_column("processed_webhook_events", "payload")
    op.drop_table("integration_checks")
    op.drop_table("daily_counters")
    op.drop_constraint("ck_analyses_quality_counts", "analyses", type_="check")
    for column in COUNTS:
        op.drop_column("analyses", column)
