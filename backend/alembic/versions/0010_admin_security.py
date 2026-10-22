"""Admin security: staff roles, step-up, the admin audit log, runtime settings, and RLS.

- users.role gains 'support' and 'superadmin' (user < support < admin < superadmin).
- auth_sessions.reauth_at: when this session last re-authenticated (step-up for
  superadmin actions).
- admin_audit_log: one row per staff mutation, written in the mutation's transaction.
  Append-only (trigger), no foreign keys, so it outlives whatever it describes.
- app_settings: runtime switches (invite-only, kill switch, ...) that override the
  env/billing.toml defaults; every write is audited by the app.
- rt_app: a NOLOGIN role that requests switch to (SET LOCAL ROLE) once a signed-in user
  is identified. It has row-level security on every user-owned table, keyed on
  app.user_id, and no privileges at all on staff, auth-flow, webhook or cost tables.
  The login role (owner) is the "service role": sign-in flows, webhooks, admin routes and
  CLIs run as it. Creating the role needs CREATEROLE once per cluster (docs/admin.md).

Revision ID: 0010_admin_security
Revises: 0009_retention
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0010_admin_security"
down_revision: str | None = "0009_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("user", "support", "admin", "superadmin")

# table -> (privileges for rt_app, row-ownership predicate). Tables not listed get nothing.
USER_TABLES = {
    "users": ("SELECT, UPDATE (name, credits_balance, referral_code, last_login_at)", "id = app_user_id()"),
    # UPDATE on one inert column only so unlink() can lock the user's own rows (FOR UPDATE).
    "accounts": ("SELECT, INSERT, DELETE, UPDATE (email_at_link)", "user_id = app_user_id()"),
    "auth_sessions": ("SELECT, INSERT, UPDATE, DELETE", "user_id = app_user_id()"),
    "consent_records": ("SELECT, INSERT", "user_id = app_user_id()"),
    "credit_transactions": ("SELECT, INSERT", "user_id = app_user_id()"),
    "passes": ("SELECT", "user_id = app_user_id()"),
    "subscriptions": ("SELECT", "user_id = app_user_id()"),
    "billing_customers": ("SELECT, INSERT", "user_id = app_user_id()"),
    "payments": ("SELECT, INSERT, UPDATE", "user_id = app_user_id()"),
    "analyses": ("SELECT, INSERT, UPDATE", "user_id = app_user_id()"),
    "downloads": ("SELECT, INSERT, UPDATE", "user_id = app_user_id()"),
    "referrals": ("SELECT, UPDATE (seen_at)", "referrer_id = app_user_id() OR referee_id = app_user_id()"),
}


def upgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", "role IN (" + ", ".join(f"'{r}'" for r in ROLES) + ")")
    op.create_index("ix_users_staff", "users", ["role"], postgresql_where=sa.text("role <> 'user'"))

    op.add_column("auth_sessions", sa.Column("reauth_at", sa.DateTime(timezone=True)))

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True)),  # NULL = the system (bootstrap CLI, scheduled jobs)
        sa.Column("actor_role", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text()),
        sa.Column("target_id", sa.Text()),
        sa.Column("reason", sa.Text()),
        sa.Column("before", JSONB()),
        sa.Column("after", JSONB()),
        sa.Column("ip_hmac", sa.Text()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_admin_audit_log"),
        sa.CheckConstraint("actor_role IN ('system', " + ", ".join(f"'{r}'" for r in ROLES) + ")",
                           name="ck_admin_audit_log_actor_role"),
        sa.CheckConstraint("action ~ '^[a-z_]+\\.[a-z_]+$'", name="ck_admin_audit_log_action"),
        sa.CheckConstraint("reason IS NULL OR length(reason) <= 500", name="ck_admin_audit_log_reason_len"),
        sa.CheckConstraint("user_agent IS NULL OR length(user_agent) <= 300", name="ck_admin_audit_log_ua_len"),
    )
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])
    op.create_index("ix_admin_audit_log_actor_created", "admin_audit_log", ["actor_id", "created_at"])
    op.create_index("ix_admin_audit_log_target", "admin_audit_log", ["target_type", "target_id", "created_at"])
    op.execute(
        """
        CREATE FUNCTION admin_audit_log_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'admin_audit_log is append-only' USING ERRCODE = 'restrict_violation';
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_audit_log_append_only
        BEFORE UPDATE OR DELETE ON admin_audit_log
        FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only();
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_audit_log_no_truncate
        BEFORE TRUNCATE ON admin_audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION admin_audit_log_append_only();
        """
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_app_settings"),
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,63}$'", name="ck_app_settings_key"),
    )

    # --- rt_app + row-level security -----------------------------------------------------------
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rt_app') THEN
            CREATE ROLE rt_app NOLOGIN NOINHERIT;
          END IF;
        END $$;
        """
    )
    op.execute("GRANT rt_app TO CURRENT_USER")  # so the login role may SET ROLE rt_app
    op.execute(
        """
        CREATE FUNCTION app_user_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO rt_app")
    op.execute("GRANT EXECUTE ON FUNCTION app_user_id() TO rt_app")
    op.execute("GRANT SELECT ON consent_notices TO rt_app")
    for table, (privileges, owner) in USER_TABLES.items():
        op.execute(f"GRANT {privileges} ON {table} TO rt_app")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY own_rows ON {table} TO rt_app USING ({owner}) WITH CHECK ({owner})")
    op.execute("GRANT USAGE ON SEQUENCE consent_records_id_seq, credit_transactions_id_seq TO rt_app")
    # The view ran with its owner's rights, which would show every user's consents.
    op.execute("ALTER VIEW current_consents SET (security_invoker = true)")
    op.execute("GRANT SELECT ON current_consents TO rt_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON current_consents FROM rt_app")
    op.execute("ALTER VIEW current_consents RESET (security_invoker)")
    for table in USER_TABLES:
        op.execute(f"DROP POLICY own_rows ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM rt_app")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM rt_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM rt_app")
    op.execute("DROP FUNCTION app_user_id()")
    # The role is cluster-wide (other databases may use it), so it stays.

    op.drop_table("app_settings")
    op.execute("DROP TRIGGER admin_audit_log_no_truncate ON admin_audit_log")
    op.execute("DROP TRIGGER admin_audit_log_append_only ON admin_audit_log")
    op.drop_table("admin_audit_log")
    op.execute("DROP FUNCTION admin_audit_log_append_only()")

    op.drop_column("auth_sessions", "reauth_at")
    op.drop_index("ix_users_staff", table_name="users")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'superadmin'")
    op.execute("UPDATE users SET role = 'user' WHERE role = 'support'")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", "role IN ('user', 'admin')")
