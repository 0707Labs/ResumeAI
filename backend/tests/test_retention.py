"""Retention purge: resume text goes after its [retention] period, billing facts stay,
and the app answers a purged analysis or download with 410 instead of crashing.
Against real Postgres, as the other billing tests."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from pydantic import ValidationError

from app.billing import analyses, referrals, retention
from app.billing.analyses import AnalysisPurged
from app.billing.config import load_billing_config
from tests.test_analyses import (  # noqa: F401 - fixtures
    NOW, begin, config, download, fetch, give_credits, inputs, new_user, pay, rules_only, run, sessions, signed_in,
    sql, start, state, tailored,
)
from tests.test_billing_admin import cli_db  # noqa: F401 - fixture

DAY = timedelta(days=1)


def execute(pg_engine, stmt, **params):
    with pg_engine.begin() as conn:
        conn.execute(text(stmt), params)


def purge(sessions, config, now=NOW):
    return asyncio.run(retention.purge_expired(sessions, config, now))


def row(pg_engine, table, rid):
    return sql(pg_engine, f"SELECT row_to_json(t) FROM {table} t WHERE id = :i", i=rid)


def downloads_of(pg_engine, aid):
    return sql(pg_engine, "SELECT json_agg(d ORDER BY created_at) FROM downloads d WHERE analysis_id = :a", a=aid)


def test_config_defaults_and_checks():
    config = load_billing_config()
    assert (config.retention.analysis_days, config.download_retention_days) == (30, 7)
    assert config.download_retention_days == config.downloads.redownload_free_days
    data = config.model_dump()
    data["products"] = {k: {kk: vv for kk, vv in v.items() if kk != "key"} for k, v in data["products"].items()}
    with pytest.raises(ValidationError, match="at least .downloads..redownload_free_days"):
        type(config).model_validate({**data, "retention": {"analysis_days": 3}})
    with pytest.raises(ValidationError, match="longer than .analyses..usable_hours"):
        type(config).model_validate({**data, "retention": {"analysis_days": 7},
                                     "analyses": {"usable_hours": 24 * 7}})
    zero_window = type(config).model_validate({**data, "downloads": {**data["downloads"], "redownload_free_days": 0}})
    assert zero_window.download_retention_days == 1


def test_purge_clears_text_past_its_period_and_keeps_what_billing_needs(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=3)
    old = NOW - 40 * DAY
    downloaded_long_ago = start(sessions, config, uid, now=old)
    pay(sessions, config, uid, downloaded_long_ago, now=old)
    downloaded_recently = start(sessions, config, uid, now=old)
    pay(sessions, config, uid, downloaded_recently, now=NOW - 10 * DAY)
    never_downloaded = start(sessions, config, uid, now=old)
    rules_only(pg_engine, never_downloaded)
    fresh = start(sessions, config, uid, now=NOW - 5 * DAY)
    before = {aid: row(pg_engine, "analyses", aid) for aid in (downloaded_long_ago, never_downloaded)}
    paid_before = sql(pg_engine, "SELECT json_agg(json_build_object('id', id, 'paid_with', paid_with, 'credits',"
                                 " credits, 'created_at', created_at) ORDER BY id) FROM downloads")
    balance_before = state(pg_engine, uid)

    assert purge(sessions, config) == retention.Purged(analyses=2, downloads=2)

    for aid in (downloaded_long_ago, never_downloaded):
        after = row(pg_engine, "analyses", aid)
        assert (after["resume"], after["jd"], after["tailored"]) == (None, None, None)
        assert after["purged_at"] is not None
        for kept in ("id", "user_id", "idempotency_key", "inputs_sha256", "llm_tailored", "tailored_at",
                     "usable_until", "created_at"):
            assert after[kept] == before[aid][kept], kept
    for aid in (downloaded_recently, fresh):  # last download or start within 30 days
        assert row(pg_engine, "analyses", aid)["resume"] == {"name": "Ada"}
    assert all(d["final_resume"] is None and d["purged_at"] for d in downloads_of(pg_engine, downloaded_long_ago))
    assert all(d["final_resume"] is None for d in downloads_of(pg_engine, downloaded_recently))  # 10 days > 7
    assert sql(pg_engine, "SELECT json_agg(json_build_object('id', id, 'paid_with', paid_with, 'credits', credits,"
                          " 'created_at', created_at) ORDER BY id) FROM downloads") == paid_before
    assert state(pg_engine, uid) == balance_before == (1, 1)

    # Idempotent: nothing more to do, and purged_at doesn't move.
    stamp = row(pg_engine, "analyses", never_downloaded)["purged_at"]
    assert purge(sessions, config, now=NOW + DAY) == retention.Purged(analyses=0, downloads=0)
    assert row(pg_engine, "analyses", never_downloaded)["purged_at"] == stamp


def test_free_allowance_and_referrals_read_the_same_after_a_purge(sessions, config, pg_engine):
    uid = new_user(pg_engine)
    month = NOW.replace(day=1, hour=1)  # NOW is 21 October; these started on the 1st
    counted = start(sessions, config, uid, now=month)
    execute(pg_engine, "UPDATE analyses SET tailored = '{}', llm_tailored = true, tailored_at = :t WHERE id = :a",
        t=month, a=counted)
    rules = start(sessions, config, uid, now=month)
    rules_only(pg_engine, rules)
    later = month + 35 * DAY  # both purged, still counted in the month they started

    def used():
        return run(sessions, lambda db: analyses.snapshot(db, config, uid, 0, month + DAY)).free_used

    def has_tailored():
        return run(sessions, lambda db: referrals._referee_has_tailored(db, uid))
    assert (used(), has_tailored()) == (1, True)
    assert purge(sessions, config, now=later).analyses == 2
    assert (used(), has_tailored()) == (1, True)


def test_purge_runs_in_batches_and_skips_an_analysis_still_in_use(sessions, config, pg_engine):
    small = config.model_copy(update={"retention": config.retention.model_copy(update={"batch_size": 2})})
    uid = new_user(pg_engine, credits=1)  # past the free tailorings, a credit balance allows starting
    ids = [start(sessions, config, uid, now=NOW - 40 * DAY) for _ in range(5)]
    execute(pg_engine, "UPDATE analyses SET usable_until = :u WHERE id = :a", u=NOW + DAY, a=ids[0])
    assert purge(sessions, small) == retention.Purged(analyses=4, downloads=0)
    assert sql(pg_engine, "SELECT count(*) FROM analyses WHERE purged_at IS NULL") == 1
    assert row(pg_engine, "analyses", ids[0])["resume"] is not None


def test_a_purged_analysis_cant_be_paid_for_or_used(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=1)
    aid = start(sessions, config, uid, now=NOW - 40 * DAY)
    purge(sessions, config)
    with pytest.raises(AnalysisPurged):
        pay(sessions, config, uid, aid)
    assert state(pg_engine, uid) == (1, 1)
    assert sql(pg_engine, "SELECT count(*) FROM downloads") == 0
    execute(pg_engine, "UPDATE analyses SET usable_until = :u WHERE id = :a", u=NOW + DAY, a=aid)
    assert run(sessions, lambda db: analyses.usable(db, uid, aid, NOW)) is None


def test_schema_refuses_half_purged_rows(sessions, config, pg_engine):
    uid = new_user(pg_engine, credits=1)
    aid = start(sessions, config, uid)
    pay(sessions, config, uid, aid)
    with pytest.raises(Exception, match="ck_analyses_purged"):
        execute(pg_engine, "UPDATE analyses SET resume = NULL WHERE id = :a", a=aid)
    with pytest.raises(Exception, match="ck_downloads_purged"):
        execute(pg_engine, "UPDATE downloads SET purged_at = now()")


def age(pg_engine, aid, days):
    """Move an analysis and its downloads back in time."""
    shift = timedelta(days=days)
    execute(pg_engine, "UPDATE analyses SET created_at = created_at - :s, usable_until = usable_until - :s,"
                   " tailored_at = tailored_at - :s WHERE id = :a", s=shift, a=aid)
    execute(pg_engine, "UPDATE downloads SET created_at = created_at - :s WHERE analysis_id = :a", s=shift, a=aid)


def test_a_re_download_after_the_purge_says_the_window_has_passed(client, signed_in, inputs, sessions, config,
                                                                    pg_engine):
    give_credits(pg_engine, signed_in, 1)
    aid = begin(client, inputs)
    tailoring = tailored(client, inputs, aid)
    link = download(client, inputs, aid, tailoring)
    assert link.json()["paid_with"] == "credit"

    age(pg_engine, aid, 40)
    assert purge(sessions, config, now=datetime.now(UTC)) == retention.Purged(analyses=1, downloads=1)

    assert fetch(client, link).status_code == 410  # the link's text is gone too
    again = download(client, inputs, aid, tailoring)
    assert (again.status_code, again.json()["detail"]) == (410, "analysis_expired")
    assert sql(pg_engine, "SELECT count(*) FROM downloads") == 1
    assert state(pg_engine, signed_in) == (0, 0)

    # Tailoring again works as usual and pays as usual.
    give_credits(pg_engine, signed_in, 1)
    fresh = begin(client, inputs)
    assert download(client, inputs, fresh, tailored(client, inputs, fresh)).json()["paid_with"] == "credit"


def test_purge_expired_cli(cli_db, sessions, config, pg_engine, capsys):
    from app.billing.cli import main
    uid = new_user(pg_engine)
    start(sessions, config, uid, now=NOW - 400 * DAY)
    assert main(["purge-expired"]) == 0
    assert "from 1 analyses and 0 downloads" in capsys.readouterr().out
    assert main(["purge-expired"]) == 0
    assert "from 0 analyses and 0 downloads" in capsys.readouterr().out
    assert sql(pg_engine, "SELECT count(*) FROM analyses WHERE purged_at IS NOT NULL") == 1


def test_purge_logs_counts_only(sessions, config, pg_engine, caplog):
    uid = new_user(pg_engine, credits=1)
    aid = start(sessions, config, uid, now=NOW - 40 * DAY)
    pay(sessions, config, uid, aid, now=NOW - 40 * DAY)
    with caplog.at_level("INFO", logger="app.billing"):
        purge(sessions, config)
    purge_lines = [r.getMessage() for r in caplog.records if "retention purge" in r.getMessage()]
    assert purge_lines == ["retention purge analyses=1 downloads=1"]
    assert not any("Ada" in r.getMessage() or str(uuid.UUID(str(aid))) in r.getMessage() for r in caplog.records
                   if "retention" in r.getMessage())
