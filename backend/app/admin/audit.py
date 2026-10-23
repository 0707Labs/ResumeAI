"""The admin audit log: one row per staff mutation.

`record()` adds the row to the caller's session without committing, so it commits or
rolls back together with the change it describes: no mutation without its entry, no
entry for a change that didn't happen. Call it before the caller's commit.

before/after are summaries (ids, counts, amounts, flags). Content keys (resume, JD,
tailored text, ticket bodies, secrets) are refused outright, and summaries are capped
in size, so the log can't become a second copy of user data.
"""

import json
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.auth.signing import ip_ref
from app.db.models import AdminAuditLog, User

MAX_SUMMARY_BYTES = 2048
FORBIDDEN_KEYS = frozenset({
    "resume", "jd", "tailored", "final_resume", "body", "text", "content", "password",
    "secret", "token", "api_key", "code",
})


class AuditError(ValueError):
    pass


def _check(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    stack: list[Any] = [summary]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            bad = FORBIDDEN_KEYS.intersection(k.lower() for k in item)
            if bad:
                raise AuditError(f"audit summary may not carry {sorted(bad)}")
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    encoded = json.dumps(summary, default=str)
    if len(encoded.encode()) > MAX_SUMMARY_BYTES:
        raise AuditError("audit summary too large; record ids and counts, not data")
    return json.loads(encoded)  # datetimes, UUIDs -> strings


def record(
    db: AsyncSession | Session,
    actor: User | None,
    action: str,
    *,
    request: Request | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | str | int | None = None,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AdminAuditLog:
    """Add an audit row for `action` ("area.verb") by `actor` (None = the system)."""
    ip = request.client.host if request is not None and request.client else None
    agent = request.headers.get("user-agent") if request is not None else None
    row = AdminAuditLog(
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else "system",
        action=action,
        target_type=target_type,
        target_id=None if target_id is None else str(target_id),
        reason=reason,
        before=_check(before),
        after=_check(after),
        ip_hmac=ip_ref(ip),
        user_agent=agent[:300] if agent else None,
    )
    db.add(row)
    return row
