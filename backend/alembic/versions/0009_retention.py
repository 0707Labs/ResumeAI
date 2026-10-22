"""Retention: resume text on analyses and downloads can be purged.

analyses.resume, .jd and .tailored and downloads.final_resume become nullable, and each
table gets purged_at: when `python -m app.billing.cli purge-expired` cleared them (see
app.billing.retention). A purged row keeps its id, owner, timestamps, inputs_sha256,
llm_tailored and tailored_at, what paid and the credits, so billing, fair-use caps, the
free allowance and referral counts read the same before and after.

Revision ID: 0009_retention
Revises: 0008_referrals
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_retention"
down_revision: str | None = "0008_referrals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Before a purge, tailored, tailored_at and llm_tailored are set together; after one,
# tailored is gone but tailored_at and llm_tailored stay (the free allowance and referrals
# read them).
TAILORED = ("(tailored_at IS NULL) = (llm_tailored IS NULL) AND (tailored IS NULL OR tailored_at IS NOT NULL)"
            " AND (purged_at IS NOT NULL OR (tailored IS NULL) = (tailored_at IS NULL))")
ANALYSIS_PURGED = ("(purged_at IS NULL) = (resume IS NOT NULL) AND (purged_at IS NULL) = (jd IS NOT NULL)"
                   " AND (purged_at IS NULL OR tailored IS NULL)")
DOWNLOAD_PURGED = "(purged_at IS NULL) = (final_resume IS NOT NULL)"


def upgrade() -> None:
    op.add_column("analyses", sa.Column("purged_at", sa.DateTime(timezone=True)))
    op.alter_column("analyses", "resume", nullable=True)
    op.alter_column("analyses", "jd", nullable=True)
    op.drop_constraint("ck_analyses_tailored", "analyses", type_="check")
    op.create_check_constraint("ck_analyses_tailored", "analyses", sa.text(TAILORED))
    op.create_check_constraint("ck_analyses_purged", "analyses", sa.text(ANALYSIS_PURGED))
    # The purge looks for unpurged rows by age.
    op.create_index("ix_analyses_unpurged_created", "analyses", ["created_at"],
                    postgresql_where=sa.text("purged_at IS NULL"))

    op.add_column("downloads", sa.Column("purged_at", sa.DateTime(timezone=True)))
    op.alter_column("downloads", "final_resume", nullable=True)
    op.create_check_constraint("ck_downloads_purged", "downloads", sa.text(DOWNLOAD_PURGED))
    op.create_index("ix_downloads_unpurged_created", "downloads", ["created_at"],
                    postgresql_where=sa.text("purged_at IS NULL"))


def downgrade() -> None:
    # Purged text can't come back. Fill purged rows with empty JSON rather than delete them,
    # so billing history, caps and the free allowance stay as they were.
    op.drop_index("ix_downloads_unpurged_created", table_name="downloads")
    op.drop_constraint("ck_downloads_purged", "downloads", type_="check")
    op.execute("UPDATE downloads SET final_resume = '{}' WHERE purged_at IS NOT NULL")
    op.alter_column("downloads", "final_resume", nullable=False)
    op.drop_column("downloads", "purged_at")

    op.drop_index("ix_analyses_unpurged_created", table_name="analyses")
    op.drop_constraint("ck_analyses_purged", "analyses", type_="check")
    op.drop_constraint("ck_analyses_tailored", "analyses", type_="check")
    op.execute("UPDATE analyses SET resume = '{}', jd = '{}' WHERE purged_at IS NOT NULL")
    op.execute("UPDATE analyses SET tailored = '{}' WHERE purged_at IS NOT NULL AND tailored_at IS NOT NULL")
    op.create_check_constraint(
        "ck_analyses_tailored", "analyses",
        sa.text("(tailored IS NULL) = (tailored_at IS NULL) AND (tailored IS NULL) = (llm_tailored IS NULL)"))
    op.alter_column("analyses", "jd", nullable=False)
    op.alter_column("analyses", "resume", nullable=False)
    op.drop_column("analyses", "purged_at")
