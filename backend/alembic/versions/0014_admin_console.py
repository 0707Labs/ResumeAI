"""Admin console: waitlist rejections and support-ticket conversations.

- waitlist.status gains 'rejected' (and rejected_at), for entries staff decline.
- support_ticket_messages: staff replies (emailed to the user) and internal notes (never
  shown to the user). No rt_app grant: users get replies by email.

Revision ID: 0014_admin_console
Revises: 0013_invites_support
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0014_admin_console"
down_revision: str | None = "0013_invites_support"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_waitlist_status", "waitlist", type_="check")
    op.create_check_constraint("ck_waitlist_status", "waitlist", "status IN ('waiting', 'invited', 'converted', 'rejected')")
    op.add_column("waitlist", sa.Column("rejected_at", sa.DateTime(timezone=True)))

    op.create_table(
        "support_ticket_messages",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ticket_id", UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", UUID(as_uuid=True)),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("emailed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_support_ticket_messages"),
        sa.ForeignKeyConstraint(["ticket_id"], ["support_tickets.id"], name="fk_support_ticket_messages_ticket_id_support_tickets",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], name="fk_support_ticket_messages_author_id_users",
                                ondelete="SET NULL"),
        sa.CheckConstraint("kind IN ('reply', 'internal_note')", name="ck_support_ticket_messages_kind"),
        sa.CheckConstraint("length(body) BETWEEN 1 AND 5000", name="ck_support_ticket_messages_body_len"),
    )
    op.create_index("ix_support_ticket_messages_ticket_created", "support_ticket_messages", ["ticket_id", "created_at"])


def downgrade() -> None:
    op.drop_table("support_ticket_messages")
    op.drop_column("waitlist", "rejected_at")
    op.execute("UPDATE waitlist SET status = 'waiting' WHERE status = 'rejected'")
    op.drop_constraint("ck_waitlist_status", "waitlist", type_="check")
    op.create_check_constraint("ck_waitlist_status", "waitlist", "status IN ('waiting', 'invited', 'converted')")
