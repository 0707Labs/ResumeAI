"""Referrals: a code per user, attribution at sign-up, rewards through the ledger.

users.referral_code: the user's own code (made on first use, unique).
pending_auth.referral_invite: in invite-only mode, this sign-up is using a referral link
as its invite.
referrals: one row per referred account (a referee is attributed once), with status
pending | rewarded | rejected, why, whether it waits for an admin (needs_review), the
signup network as an HMAC (never the IP itself), and what was paid. Credits move only
through credit_transactions (reason 'referral', reference_id = referral id).

Revision ID: 0008_referrals
Revises: 0007_analyses
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0008_referrals"
down_revision: str | None = "0007_analyses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("referral_code", sa.Text()))
    op.create_unique_constraint("uq_users_referral_code", "users", ["referral_code"])
    op.add_column("pending_auth", sa.Column("referral_invite", sa.Boolean(), nullable=False,
                                            server_default=sa.text("false")))
    op.create_table(
        "referrals",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("referrer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("referee_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text()),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("used_as_invite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ip_hmac", sa.Text()),
        sa.Column("reward_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invitee_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("rewarded_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", UUID(as_uuid=True)),
        sa.Column("reversed_at", sa.DateTime(timezone=True)),
        sa.Column("seen_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name="pk_referrals"),
        sa.ForeignKeyConstraint(["referrer_id"], ["users.id"], name="fk_referrals_referrer_id_users",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["referee_id"], ["users.id"], name="fk_referrals_referee_id_users",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name="fk_referrals_decided_by_users",
                                ondelete="SET NULL"),
        sa.UniqueConstraint("referee_id", name="uq_referrals_referee_id"),
        sa.CheckConstraint("status IN ('pending', 'rewarded', 'rejected')", name="ck_referrals_status"),
        sa.CheckConstraint("referrer_id <> referee_id", name="ck_referrals_not_self"),
        sa.CheckConstraint("status <> 'rewarded' OR rewarded_at IS NOT NULL", name="ck_referrals_rewarded"),
        sa.CheckConstraint("reversed_at IS NULL OR status = 'rejected'", name="ck_referrals_reversed"),
    )
    op.create_index("ix_referrals_referrer_created", "referrals", ["referrer_id", "created_at"])
    op.create_index("ix_referrals_review", "referrals", ["created_at"], postgresql_where=sa.text("needs_review"))
    op.create_index("ix_referrals_ip", "referrals", ["ip_hmac", "created_at"],
                    postgresql_where=sa.text("ip_hmac IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("referrals")
    op.drop_column("pending_auth", "referral_invite")
    op.drop_constraint("uq_users_referral_code", "users", type_="unique")
    op.drop_column("users", "referral_code")
