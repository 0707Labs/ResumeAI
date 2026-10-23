"""Plain per-day counts for the admin dashboard: resume parse failures and warnings by
code, landing page views. A count is a name and a number; nothing about who or what.

`bump()` only adds to an in-process tally, so the paths that count (resume parsing,
signed-out use) never touch the database and never slow down. The app flushes the tally
into daily_counters every minute and at shutdown (`flusher()`); losing a minute's counts
in a crash is fine for these numbers.
"""

import asyncio
import contextlib
import logging
import re
import threading
from collections import Counter
from datetime import UTC, date, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyCounter

log = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z][a-z0-9_.:]{0,79}$")
FLUSH_SECONDS = 60

_lock = threading.Lock()
_tally: Counter[tuple[date, str]] = Counter()


def bump(name: str, n: int = 1) -> None:
    if not NAME.match(name) or n <= 0:
        return
    with _lock:
        _tally[(datetime.now(UTC).date(), name)] += n


def take() -> dict[tuple[date, str], int]:
    """Empty the tally and return what it held."""
    with _lock:
        out = dict(_tally)
        _tally.clear()
    return out


async def flush(db: AsyncSession) -> int:
    """Add the tally to daily_counters. Commits. On failure the counts go back."""
    pending = take()
    if not pending:
        return 0
    try:
        for (day, name), n in pending.items():
            stmt = insert(DailyCounter).values(day=day, name=name, count=n)
            await db.execute(stmt.on_conflict_do_update(index_elements=["day", "name"],
                                                        set_={"count": DailyCounter.count + stmt.excluded.count}))
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - counting must never break anything
        await db.rollback()
        with _lock:
            _tally.update(pending)
        log.warning("could not flush counters: %s", exc.__class__.__name__)
        return 0
    return len(pending)


async def flusher() -> None:
    """Background task: flush every minute, and once more when cancelled (shutdown)."""
    from app.db.session import get_sessionmaker

    async def once() -> None:
        async with get_sessionmaker()() as db:
            await flush(db)

    try:
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            await once()
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await asyncio.shield(once())
        raise
