"""Pre-deploy step: `python -m app.migrate` (backend/railway.json).

Runs `alembic upgrade head`, except when the database is already at a revision this code
doesn't know. That happens when a deploy is rolled back to older code after its migration
ran: plain `alembic upgrade head` then fails ("Can't locate revision") and would block the
rollback. Migrations are additive (docs/deploy.md, "Railway"), so older code runs on the
newer schema; this prints what it found and exits 0. Undoing a migration is a deliberate,
separate step (docs/deploy.md, "Rollback")."""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool

from app.config import migration_database_url

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def current_revisions(url: str) -> set[str]:
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            return set(MigrationContext.configure(conn).get_current_heads())
    finally:
        engine.dispose()


def main(url: str | None = None) -> int:
    url = url or migration_database_url()
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    known = {rev.revision for rev in ScriptDirectory.from_config(cfg).walk_revisions()}
    unknown = current_revisions(url) - known
    if unknown:
        print(f"Database is at {', '.join(sorted(unknown))}, newer than this code "
              f"(head {ScriptDirectory.from_config(cfg).get_current_head()}): a rollback. Not migrating.")
        return 0
    command.upgrade(cfg, "head")
    return 0


if __name__ == "__main__":
    sys.exit(main())
