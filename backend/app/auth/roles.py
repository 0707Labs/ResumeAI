"""Staff roles and what each may do. The one place that answers "may this caller...?".

users.role is read from the database on every request (via the session lookup); nothing
the client sends can raise it. Admin routes depend on `require(capability)`, never on a
role name, and run as the service role (no row-level scoping) because they read across
users. tests/test_admin_security.py fails if an /api/admin route has no capability.

Capabilities marked step-up also need a sign-in through an existing login method within
STEP_UP_WINDOW (auth_sessions.reauth_at); otherwise 401 reauth_required, and the UI sends
the caller through /signin again.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import Depends, HTTPException, Request

from app.auth.deps import optional_user
from app.auth.sessions import SignedIn
from app.db.models import User

Role = Literal["user", "support", "admin", "superadmin"]
STAFF: tuple[Role, ...] = ("support", "admin", "superadmin")
STEP_UP_WINDOW = timedelta(minutes=10)

Capability = Literal[
    "staff.access",        # see /admin at all
    "users.read",          # user metadata; never resume or JD text
    "tickets.read",
    "tickets.write",       # reply, internal note, assign, status
    "audit.read",
    "users.write",         # suspend, force sign-out
    "credits.adjust",      # through the ledger, reason admin_adjust
    "passes.grant",
    "invites.write",       # admin codes, bulk, revoke, extend; waitlist decisions
    "referrals.decide",
    "billing.read",        # revenue, payments, subscriptions, billing reviews
    "billing.write",       # refunds, disputes, resolving billing reviews
    "costs.read",
    "quality.read",
    "integrations.read",   # status and health checks; never secret values
    "users.delete",
    "roles.write",
    "settings.write",      # flags, kill switch, budgets, model config, legal versions
    "secrets.hint",        # last 4 characters of a configured secret
]

_SUPPORT: frozenset[Capability] = frozenset({"staff.access", "users.read", "tickets.read", "tickets.write"})
_ADMIN: frozenset[Capability] = _SUPPORT | {
    "audit.read", "users.write", "credits.adjust", "passes.grant", "invites.write", "referrals.decide",
    "billing.read", "billing.write", "costs.read", "quality.read", "integrations.read",
}
_SUPERADMIN: frozenset[Capability] = _ADMIN | {"users.delete", "roles.write", "settings.write", "secrets.hint"}

CAPABILITIES: dict[str, frozenset[Capability]] = {
    "user": frozenset(),
    "support": _SUPPORT,
    "admin": _ADMIN,
    "superadmin": _SUPERADMIN,
}
STEP_UP: frozenset[Capability] = frozenset({"users.delete", "roles.write", "settings.write", "secrets.hint"})


def can(role: str, capability: Capability) -> bool:
    return capability in CAPABILITIES.get(role, frozenset())


def capabilities(role: str) -> list[Capability]:
    return sorted(CAPABILITIES.get(role, frozenset()))


def require(capability: Capability):
    """FastAPI dependency: the signed-in, active staff member allowed `capability`.
    401 without a session, 403 otherwise (the same answer whatever the reason, so the
    route's existence and the caller's role aren't disclosed beyond "not for you")."""

    async def dependency(request: Request, signed_in: SignedIn | None = Depends(optional_user)) -> User:
        if signed_in is None:
            raise HTTPException(status_code=401, detail="not_signed_in")
        user = signed_in.user
        if user.status != "active" or not can(user.role, capability):
            raise HTTPException(status_code=403, detail="forbidden")
        if capability in STEP_UP:
            fresh = signed_in.reauth_at is not None and datetime.now(UTC) - signed_in.reauth_at < STEP_UP_WINDOW
            if not fresh:
                raise HTTPException(status_code=401, detail="reauth_required")
        request.state.staff = user  # for the audit helper
        return user

    dependency.capability = capability  # type: ignore[attr-defined]  # read by the route audit test
    return dependency
