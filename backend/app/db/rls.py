"""Row-level security for signed-in requests.

Once `current_user` knows who is calling, the request's DB session switches to the
rt_app role with app.user_id set (migration 0010). From then on Postgres itself limits
every query to that user's rows, and staff, auth-flow, webhook and cost tables are
unreadable. Both settings are transaction-local (SET LOCAL / set_config(..., true)), so
they are re-applied at the start of every later transaction in the same session and can
never leak to another request through the connection pool.

Code that must touch rows beyond the caller's (rewarding a referrer, checking that a
provider identity isn't linked elsewhere, account deletion) wraps exactly that work in
`service_scope(db)`. Keep those blocks small: each one is a deliberate exception.

Sessions that never call user_scope (sign-in flows, webhooks, admin routes, CLIs) run as
the login role, i.e. the service role.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

ROLE = "rt_app"
_KEY = "rls_user_id"


def _apply(conn: Connection, user_id: uuid.UUID) -> None:
    conn.exec_driver_sql(f"SET LOCAL ROLE {ROLE}")
    conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})


@event.listens_for(Session, "after_begin")
def _reapply(session: Session, _tx: SessionTransaction, conn: Connection) -> None:
    user_id = session.info.get(_KEY)
    if user_id is not None:
        _apply(conn, user_id)


async def user_scope(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Limit this session to `user_id`'s rows from now on, including the open transaction."""
    db.sync_session.info[_KEY] = user_id
    if db.in_transaction():
        await db.run_sync(lambda s: _apply(s.connection(), user_id))


def scoped_user(db: AsyncSession) -> uuid.UUID | None:
    return db.sync_session.info.get(_KEY)


@asynccontextmanager
async def service_scope(db: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Run the block as the service role, then return to the user's scope.
    Works inside or outside a transaction; commits inside the block are fine."""
    user_id = db.sync_session.info.pop(_KEY, None)
    if user_id is not None and db.in_transaction():
        await db.execute(text("RESET ROLE"))
    try:
        yield db
    except BaseException:
        # The transaction may be aborted; the caller rolls back and the next one re-applies.
        if user_id is not None:
            db.sync_session.info[_KEY] = user_id
        raise
    if user_id is not None:
        db.sync_session.info[_KEY] = user_id
        if db.in_transaction():
            await db.run_sync(lambda s: _apply(s.connection(), user_id))
