"""The pre-deploy migration step upgrades as usual and doesn't block a rollback."""

from sqlalchemy import create_engine, text

from app import migrate


def version(pg_url) -> str:
    engine = create_engine(pg_url)
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()


def set_version(pg_url, rev: str) -> None:
    engine = create_engine(pg_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": rev})
    finally:
        engine.dispose()


def test_upgrades_to_head(pg_url):
    head = version(pg_url)
    assert migrate.main(pg_url) == 0
    assert version(pg_url) == head


def test_a_database_ahead_of_the_code_is_left_alone(pg_url, capsys):
    """Rolled back to older code: plain `alembic upgrade head` would fail here."""
    head = version(pg_url)
    set_version(pg_url, "0099_from_a_newer_deploy")
    try:
        assert migrate.main(pg_url) == 0
        assert version(pg_url) == "0099_from_a_newer_deploy"
        assert "a rollback. Not migrating." in capsys.readouterr().out
    finally:
        set_version(pg_url, head)
