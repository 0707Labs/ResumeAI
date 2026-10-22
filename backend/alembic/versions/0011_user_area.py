"""User area: onboarding, job preferences, saved resumes, analysis metadata.

- users.onboarded_at: set when the first-login wizard is finished or skipped. Existing
  accounts are backfilled (they've used the app already), so only new sign-ups see it.
- job_preferences: one row per user, the onboarding/profile answers.
- resumes + resume_versions: base resumes the user keeps. Each edit or re-upload adds a
  version (versions are never updated; deleting a resume deletes its versions). Saved
  resumes are user-managed, so the retention purge doesn't touch them; the user deletes them.
- analyses gains metadata for lists and the dashboard: the resume it came from, the job
  title and company, ATS before/after, and the first mentor action (mentor_tip, text, so
  the retention purge clears it with the rest of the analysis text).
- rt_app gets the new user-owned tables under the same own-rows policy as 0010.

Revision ID: 0011_user_area
Revises: 0010_admin_security
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision: str = "0011_user_area"
down_revision: str | None = "0010_admin_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SENIORITY = ("intern", "junior", "mid", "senior", "lead", "principal")
WORK_MODES = ("remote", "hybrid", "onsite")
EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "internship", "freelance")
ANALYSIS_PURGED = ("(purged_at IS NULL) = (resume IS NOT NULL) AND (purged_at IS NULL) = (jd IS NOT NULL)"
                   " AND (purged_at IS NULL OR tailored IS NULL)")
ANALYSIS_PURGED_NEW = ANALYSIS_PURGED + " AND (purged_at IS NULL OR mentor_tip IS NULL)"

NEW_TABLES = {
    "job_preferences": "SELECT, INSERT, UPDATE",
    "resumes": "SELECT, INSERT, UPDATE, DELETE",
    "resume_versions": "SELECT, INSERT, DELETE",
}


def _array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(f"'{v}'" for v in values) + "]::text[]"


def _short_list(column: str, items: int = 10, length: int = 80) -> str:
    return f"text_list_ok({column}, {items}, {length})"


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarded_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE users SET onboarded_at = activated_at")
    op.execute("GRANT UPDATE (onboarded_at) ON users TO rt_app")

    # CHECK constraints can't hold subqueries; a list's size and item lengths go through this.
    op.execute(
        """
        CREATE FUNCTION text_list_ok(vals text[], max_items int, max_len int) RETURNS boolean
        LANGUAGE sql IMMUTABLE AS $$
          SELECT cardinality(vals) <= max_items
             AND coalesce(bool_and(length(v) BETWEEN 1 AND max_len), true) FROM unnest(vals) v
        $$;
        """
    )
    text_array = ARRAY(sa.Text())
    empty = sa.text("'{}'::text[]")
    op.create_table(
        "job_preferences",
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_roles", text_array, server_default=empty, nullable=False),
        sa.Column("seniority", sa.Text()),
        sa.Column("industries", text_array, server_default=empty, nullable=False),
        sa.Column("locations", text_array, server_default=empty, nullable=False),
        sa.Column("work_modes", text_array, server_default=empty, nullable=False),
        sa.Column("employment_types", text_array, server_default=empty, nullable=False),
        sa.Column("notice_period_days", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_job_preferences"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_job_preferences_user_id_users", ondelete="CASCADE"),
        sa.CheckConstraint("seniority IS NULL OR seniority IN (" + ", ".join(f"'{s}'" for s in SENIORITY) + ")",
                           name="ck_job_preferences_seniority"),
        sa.CheckConstraint(f"work_modes <@ {_array(WORK_MODES)}", name="ck_job_preferences_work_modes"),
        sa.CheckConstraint(f"employment_types <@ {_array(EMPLOYMENT_TYPES)}", name="ck_job_preferences_employment_types"),
        sa.CheckConstraint("notice_period_days IS NULL OR notice_period_days BETWEEN 0 AND 365",
                           name="ck_job_preferences_notice_period"),
        sa.CheckConstraint(_short_list("target_roles"), name="ck_job_preferences_target_roles"),
        sa.CheckConstraint(_short_list("industries"), name="ck_job_preferences_industries"),
        sa.CheckConstraint(_short_list("locations"), name="ck_job_preferences_locations"),
    )

    op.create_table(
        "resumes",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_resumes"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_resumes_user_id_users", ondelete="CASCADE"),
        sa.CheckConstraint("length(title) BETWEEN 1 AND 120", name="ck_resumes_title"),
    )
    op.create_index("ix_resumes_user_created", "resumes", ["user_id", "created_at"])
    op.create_index("ix_resumes_one_default", "resumes", ["user_id"], unique=True,
                    postgresql_where=sa.text("is_default"))

    op.create_table(
        "resume_versions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("resume_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),  # = the resume's; keeps RLS a column check
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", JSONB(), nullable=False),  # the parsed Resume, bullet ids included
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_resume_versions"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], name="fk_resume_versions_resume_id_resumes",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_resume_versions_user_id_users",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("resume_id", "version", name="uq_resume_versions_resume_id_version"),
        sa.CheckConstraint("version >= 1", name="ck_resume_versions_version"),
        sa.CheckConstraint("source IN ('upload', 'paste', 'edit')", name="ck_resume_versions_source"),
        sa.CheckConstraint("file_name IS NULL OR length(file_name) <= 200", name="ck_resume_versions_file_name"),
    )
    op.create_index("ix_resume_versions_user_id", "resume_versions", ["user_id"])
    op.execute(
        """
        CREATE FUNCTION resume_versions_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'resume_versions are never updated; add a version' USING ERRCODE = 'restrict_violation';
        END $$;
        """
    )
    op.execute("CREATE TRIGGER resume_versions_immutable BEFORE UPDATE ON resume_versions"
               " FOR EACH ROW EXECUTE FUNCTION resume_versions_immutable()")
    # A version's owner must be its resume's owner (RLS checks user_id on each table).
    op.execute(
        """
        CREATE FUNCTION resume_versions_owner() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM resumes WHERE id = NEW.resume_id AND user_id = NEW.user_id) THEN
            RAISE EXCEPTION 'resume version owner must match the resume' USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute("CREATE TRIGGER resume_versions_owner BEFORE INSERT ON resume_versions"
               " FOR EACH ROW EXECUTE FUNCTION resume_versions_owner()")

    op.add_column("analyses", sa.Column("resume_id", UUID(as_uuid=True)))
    op.create_foreign_key("fk_analyses_resume_id_resumes", "analyses", "resumes", ["resume_id"], ["id"],
                          ondelete="SET NULL")
    op.add_column("analyses", sa.Column("job_title", sa.Text()))
    op.add_column("analyses", sa.Column("company", sa.Text()))
    op.add_column("analyses", sa.Column("ats_before", sa.Numeric(4, 1)))
    op.add_column("analyses", sa.Column("ats_after", sa.Numeric(4, 1)))
    op.add_column("analyses", sa.Column("mentor_tip", sa.Text()))
    op.create_check_constraint("ck_analyses_ats", "analyses",
                               "(ats_before IS NULL OR ats_before BETWEEN 0 AND 100)"
                               " AND (ats_after IS NULL OR ats_after BETWEEN 0 AND 100)")
    op.create_check_constraint("ck_analyses_meta_len", "analyses",
                               "(job_title IS NULL OR length(job_title) <= 200)"
                               " AND (company IS NULL OR length(company) <= 200)"
                               " AND (mentor_tip IS NULL OR length(mentor_tip) <= 1000)")
    op.drop_constraint("ck_analyses_purged", "analyses", type_="check")
    op.create_check_constraint("ck_analyses_purged", "analyses", sa.text(ANALYSIS_PURGED_NEW))
    op.create_index("ix_analyses_resume_id", "analyses", ["resume_id"],
                    postgresql_where=sa.text("resume_id IS NOT NULL"))

    for table, privileges in NEW_TABLES.items():
        op.execute(f"GRANT {privileges} ON {table} TO rt_app")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY own_rows ON {table} TO rt_app"
                   " USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())")


def downgrade() -> None:
    for table in NEW_TABLES:
        op.execute(f"DROP POLICY own_rows ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM rt_app")
    op.drop_index("ix_analyses_resume_id", table_name="analyses")
    op.drop_constraint("ck_analyses_purged", "analyses", type_="check")
    op.create_check_constraint("ck_analyses_purged", "analyses", sa.text(ANALYSIS_PURGED))
    op.drop_constraint("ck_analyses_meta_len", "analyses", type_="check")
    op.drop_constraint("ck_analyses_ats", "analyses", type_="check")
    for column in ("mentor_tip", "ats_after", "ats_before", "company", "job_title"):
        op.drop_column("analyses", column)
    op.drop_constraint("fk_analyses_resume_id_resumes", "analyses", type_="foreignkey")
    op.drop_column("analyses", "resume_id")

    op.execute("DROP TRIGGER resume_versions_owner ON resume_versions")
    op.execute("DROP TRIGGER resume_versions_immutable ON resume_versions")
    op.drop_table("resume_versions")
    op.execute("DROP FUNCTION resume_versions_owner()")
    op.execute("DROP FUNCTION resume_versions_immutable()")
    op.drop_table("resumes")
    op.drop_table("job_preferences")
    op.execute("DROP FUNCTION text_list_ok(text[], int, int)")

    op.execute("REVOKE UPDATE (onboarded_at) ON users FROM rt_app")
    op.drop_column("users", "onboarded_at")
