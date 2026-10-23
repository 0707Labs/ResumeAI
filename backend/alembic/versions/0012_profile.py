"""Profile: avatars, phone, the provider picture hand-off, and deleting a tailoring.

- user_avatars: the user's picture as we re-encoded it (WebP, at most 256 KB). Never a
  link to a provider: the browser only talks to our origin. source says whether it came
  from Google/GitHub at sign-in or from an upload.
- users.avatar_removed_at: the user removed their picture, so sign-in doesn't put the
  provider's back. users.phone: optional, E.164.
- pending_auth.picture_url: a new sign-up's provider picture (https, from the verified
  identity), imported once the account exists. Deleted with the pending row.
- analyses.deleted_at: a tailoring the user deleted. Deleting purges its text at once
  (purged_at); the row stays so billing, fair-use caps and referrals count the same.

Revision ID: 0012_profile
Revises: 0011_user_area
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0012_profile"
down_revision: str | None = "0011_user_area"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_AVATAR_BYTES = 262_144


def upgrade() -> None:
    op.create_table(
        "user_avatars",
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_avatars"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_avatars_user_id_users", ondelete="CASCADE"),
        sa.CheckConstraint("content_type = 'image/webp'", name="ck_user_avatars_content_type"),
        sa.CheckConstraint(f"octet_length(data) BETWEEN 1 AND {MAX_AVATAR_BYTES}", name="ck_user_avatars_size"),
        sa.CheckConstraint("source IN ('provider', 'upload')", name="ck_user_avatars_source"),
    )
    op.add_column("users", sa.Column("avatar_removed_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("phone", sa.Text()))
    op.create_check_constraint("ck_users_phone", "users", "phone IS NULL OR phone ~ '^\\+[1-9][0-9]{6,14}$'")
    op.add_column("pending_auth", sa.Column("picture_url", sa.Text()))
    op.create_check_constraint("ck_pending_auth_picture_url", "pending_auth",
                               "picture_url IS NULL OR (picture_url LIKE 'https://%' AND length(picture_url) <= 1000)")
    op.add_column("analyses", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_check_constraint("ck_analyses_deleted", "analyses", "deleted_at IS NULL OR purged_at IS NOT NULL")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_avatars TO rt_app")
    op.execute("ALTER TABLE user_avatars ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY own_rows ON user_avatars TO rt_app"
               " USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())")
    op.execute("GRANT UPDATE (phone, avatar_removed_at) ON users TO rt_app")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (phone, avatar_removed_at) ON users FROM rt_app")
    op.execute("DROP POLICY own_rows ON user_avatars")
    op.execute("REVOKE ALL ON user_avatars FROM rt_app")
    op.drop_constraint("ck_analyses_deleted", "analyses", type_="check")
    op.drop_column("analyses", "deleted_at")
    op.drop_constraint("ck_pending_auth_picture_url", "pending_auth", type_="check")
    op.drop_column("pending_auth", "picture_url")
    op.drop_constraint("ck_users_phone", "users", type_="check")
    op.drop_column("users", "phone")
    op.drop_column("users", "avatar_removed_at")
    op.drop_table("user_avatars")
