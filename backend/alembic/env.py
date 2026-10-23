"""Migrations run synchronously over psycopg 3 (the app uses the same driver async).

The URL is RT_MIGRATION_DATABASE_URL, else RT_DATABASE_URL, unless a caller (the test
fixtures) sets `sqlalchemy.url` on the Config object. Deploys point RT_MIGRATION_DATABASE_URL
at a direct (unpooled) connection as the same login role (docs/deploy.md)."""

import os

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.db.models import Base

config = context.config
target_metadata = Base.metadata


def database_url() -> str:
    return (config.get_main_option("sqlalchemy.url") or os.environ.get("RT_MIGRATION_DATABASE_URL")
            or get_settings().database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
