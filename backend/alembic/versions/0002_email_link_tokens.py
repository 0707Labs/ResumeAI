"""Email tokens for adding email sign-in to an existing account.

A 'link' token is bound to the signed-in user who asked for it, so a sign-in
link can never be used to attach an address to someone else's account.

Revision ID: 0002_email_link_tokens
Revises: 0001_core_auth
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002_email_link_tokens"
down_revision: str | None = "0001_core_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("email_tokens", sa.Column("user_id", UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_email_tokens_user_id_users", "email_tokens", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_email_tokens_user_id", "email_tokens", ["user_id"])
    op.drop_constraint("ck_email_tokens_purpose", "email_tokens", type_="check")
    op.create_check_constraint(
        "ck_email_tokens_purpose", "email_tokens", "purpose IN ('login', 'verify_pending', 'link')"
    )
    op.create_check_constraint(
        "ck_email_tokens_user_matches_purpose", "email_tokens", "(purpose = 'link') = (user_id IS NOT NULL)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM email_tokens WHERE purpose = 'link'")
    op.drop_constraint("ck_email_tokens_user_matches_purpose", "email_tokens", type_="check")
    op.drop_constraint("ck_email_tokens_purpose", "email_tokens", type_="check")
    op.create_check_constraint(
        "ck_email_tokens_purpose", "email_tokens", "purpose IN ('login', 'verify_pending')"
    )
    op.drop_index("ix_email_tokens_user_id", "email_tokens")
    op.drop_constraint("fk_email_tokens_user_id_users", "email_tokens", type_="foreignkey")
    op.drop_column("email_tokens", "user_id")
