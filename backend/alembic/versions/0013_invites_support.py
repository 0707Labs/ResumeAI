"""Personal invites with a hard per-user quota, and support tickets.

- invites.kind: 'admin' (CLI / admin dashboard), 'personal' (a user invited a friend by
  email), 'waitlist' (approved from the waitlist). Plus campaign and batch_id for bulk sets.
- users.invites_created: invite slots used. One quota covers a user's email invites and
  sign-ups that used their referral link as the invite. Only the functions below change it,
  and each locks the user's row first, so concurrent requests can't go past the limit:
    create_user_invite(user, limit, code_hash, hint, email, expires) -> invite id
    revoke_user_invite(user, invite) -> bool  (the slot comes back only if never redeemed)
    take_invite_slot(user, limit) -> bool      (a referral-link sign-up)
  They're SECURITY DEFINER (rt_app can't write the counter or invites itself) and refuse a
  signed-in caller acting for another user. The limit comes from billing.toml
  ([referrals].invites_per_user) and is capped at 100 here.
- Existing referral-link invites are counted into invites_created.
- support_tickets: the contact form. A user sees their own; staff work them in /admin.

Revision ID: 0013_invites_support
Revises: 0012_profile
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0013_invites_support"
down_revision: str | None = "0012_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORIES = ("support", "feedback", "fabrication_report", "grievance", "billing", "privacy")
STATUSES = ("open", "pending", "closed")

GUARD = """
  IF app_user_id() IS NOT NULL AND app_user_id() <> p_user THEN
    RAISE EXCEPTION 'not_allowed' USING ERRCODE = 'insufficient_privilege';
  END IF;
"""


def upgrade() -> None:
    op.add_column("invites", sa.Column("kind", sa.Text(), server_default="admin", nullable=False))
    op.add_column("invites", sa.Column("campaign", sa.Text()))
    op.add_column("invites", sa.Column("batch_id", UUID(as_uuid=True)))
    op.create_check_constraint("ck_invites_kind", "invites", "kind IN ('admin', 'personal', 'waitlist')")
    op.create_check_constraint("ck_invites_campaign_len", "invites", "campaign IS NULL OR length(campaign) <= 80")
    op.create_check_constraint("ck_invites_personal", "invites",
                               "kind <> 'personal' OR (created_by IS NOT NULL AND email IS NOT NULL AND max_uses = 1)")
    op.create_index("ix_invites_created_by_created", "invites", ["created_by", "created_at"],
                    postgresql_where=sa.text("created_by IS NOT NULL"))
    op.create_index("ix_invites_batch_id", "invites", ["batch_id"], postgresql_where=sa.text("batch_id IS NOT NULL"))

    op.add_column("users", sa.Column("invites_created", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint("ck_users_invites_created", "users", "invites_created >= 0")
    op.execute("""
        UPDATE users u SET invites_created = r.n
          FROM (SELECT referrer_id, count(*) AS n FROM referrals WHERE used_as_invite GROUP BY referrer_id) r
         WHERE r.referrer_id = u.id
    """)

    op.execute(f"""
        CREATE FUNCTION create_user_invite(p_user uuid, p_limit int, p_code_hash text, p_hint text, p_email text,
                                           p_expires timestamptz) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE used int; new_id uuid;
        BEGIN
          {GUARD}
          SELECT invites_created INTO used FROM users WHERE id = p_user AND deleted_at IS NULL FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'no_user' USING ERRCODE = 'no_data_found';
          END IF;
          IF used >= LEAST(GREATEST(p_limit, 0), 100) THEN
            RAISE EXCEPTION 'invite_limit' USING ERRCODE = 'check_violation';
          END IF;
          INSERT INTO invites (code_hash, code_hint, email, created_by, max_uses, expires_at, kind)
          VALUES (p_code_hash, p_hint, lower(p_email), p_user, 1, p_expires, 'personal')
          RETURNING id INTO new_id;
          UPDATE users SET invites_created = used + 1 WHERE id = p_user;
          RETURN new_id;
        END $$;
    """)
    op.execute(f"""
        CREATE FUNCTION revoke_user_invite(p_user uuid, p_invite uuid) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE redeemed int;
        BEGIN
          {GUARD}
          PERFORM 1 FROM users WHERE id = p_user FOR UPDATE;
          UPDATE invites SET revoked_at = now()
           WHERE id = p_invite AND created_by = p_user AND kind = 'personal' AND revoked_at IS NULL
          RETURNING uses INTO redeemed;
          IF NOT FOUND THEN
            RETURN false;
          END IF;
          IF redeemed = 0 THEN
            UPDATE users SET invites_created = GREATEST(invites_created - 1, 0) WHERE id = p_user;
          END IF;
          RETURN true;
        END $$;
    """)
    op.execute("""
        CREATE FUNCTION take_invite_slot(p_user uuid, p_limit int) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE used int;
        BEGIN
          SELECT invites_created INTO used FROM users WHERE id = p_user AND deleted_at IS NULL FOR UPDATE;
          IF NOT FOUND OR used >= LEAST(GREATEST(p_limit, 0), 100) THEN
            RETURN false;
          END IF;
          UPDATE users SET invites_created = used + 1 WHERE id = p_user;
          RETURN true;
        END $$;
    """)
    for fn in ("create_user_invite(uuid, int, text, text, text, timestamptz)", "revoke_user_invite(uuid, uuid)",
               "take_invite_slot(uuid, int)"):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION create_user_invite(uuid, int, text, text, text, timestamptz) TO rt_app")
    op.execute("GRANT EXECUTE ON FUNCTION revoke_user_invite(uuid, uuid) TO rt_app")
    # take_invite_slot runs during sign-up (service role): no rt_app grant.

    op.create_table(
        "support_tickets",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("assignee_id", UUID(as_uuid=True)),
        sa.Column("analysis_id", UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_support_tickets"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_support_tickets_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], name="fk_support_tickets_assignee_id_users",
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], name="fk_support_tickets_analysis_id_analyses",
                                ondelete="SET NULL"),
        sa.CheckConstraint("category IN (" + ", ".join(f"'{c}'" for c in CATEGORIES) + ")",
                           name="ck_support_tickets_category"),
        sa.CheckConstraint("status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")", name="ck_support_tickets_status"),
        sa.CheckConstraint("length(subject) BETWEEN 1 AND 150", name="ck_support_tickets_subject_len"),
        sa.CheckConstraint("length(body) BETWEEN 1 AND 5000", name="ck_support_tickets_body_len"),
        sa.CheckConstraint("email = lower(email)", name="ck_support_tickets_email_lower"),
    )
    op.create_index("ix_support_tickets_user_created", "support_tickets", ["user_id", "created_at"])
    op.create_index("ix_support_tickets_open", "support_tickets", ["created_at"],
                    postgresql_where=sa.text("status <> 'closed'"))
    op.execute("GRANT SELECT, INSERT ON support_tickets TO rt_app")
    op.execute("ALTER TABLE support_tickets ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY own_rows ON support_tickets TO rt_app"
               " USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())")


def downgrade() -> None:
    op.execute("DROP POLICY own_rows ON support_tickets")
    op.drop_table("support_tickets")
    op.execute("DROP FUNCTION take_invite_slot(uuid, int)")
    op.execute("DROP FUNCTION revoke_user_invite(uuid, uuid)")
    op.execute("DROP FUNCTION create_user_invite(uuid, int, text, text, text, timestamptz)")
    op.drop_constraint("ck_users_invites_created", "users", type_="check")
    op.drop_column("users", "invites_created")
    op.drop_index("ix_invites_batch_id", table_name="invites")
    op.drop_index("ix_invites_created_by_created", table_name="invites")
    op.drop_constraint("ck_invites_personal", "invites", type_="check")
    op.drop_constraint("ck_invites_campaign_len", "invites", type_="check")
    op.drop_constraint("ck_invites_kind", "invites", type_="check")
    for column in ("batch_id", "campaign", "kind"):
        op.drop_column("invites", column)
