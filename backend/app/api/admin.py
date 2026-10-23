"""/api/admin: staff only. Every route depends on require(capability) (app.auth.roles),
runs as the service role, and every mutation writes an admin_audit_log row in its own
transaction (app.admin.audit). Responses carry metadata only, never resume or JD text.

Routers: `router` (settings, audit log, staff roles) and `billing_router` (the billing
dashboard, /api/admin/billing). Referral decisions live in app/api/referrals.py.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import audit
from app.admin import settings as runtime
from app.api.billing import billing_config
from app.auth.csrf import require_csrf
from app.auth.ratelimit import rate_limit
from app.auth.roles import Role, require
from app.billing.admin import overview, resolve_review
from app.billing.config import BillingConfig
from app.db.models import AdminAuditLog, BillingReview, User
from app.db.session import get_db

router = APIRouter(prefix="/api/admin")
billing_router = APIRouter(prefix="/api/admin/billing")

# Stricter than the user-facing limits; per client IP like the rest (app.auth.ratelimit).
READ_LIMIT = rate_limit("admin_read", 120, 60)
WRITE_LIMIT = rate_limit("admin_write", 30, 60)
WRITE = [Depends(WRITE_LIMIT), Depends(require_csrf)]


class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


# --- settings ----------------------------------------------------------------------------------


class SettingsOut(BaseModel):
    values: dict[str, Any]
    overridden: list[str]
    defaults: dict[str, Any]


def _settings_out(current: runtime.Current) -> SettingsOut:
    return SettingsOut(values=current.values.model_dump(mode="json"), overridden=sorted(current.overridden),
                       defaults=runtime.defaults())


@router.get("/settings", dependencies=[Depends(READ_LIMIT)])
async def get_settings(_: User = Depends(require("audit.read")), db: AsyncSession = Depends(get_db)) -> SettingsOut:
    return _settings_out(await runtime.read_all(db))


class SettingIn(Reason):
    value: Any


@router.put("/settings/{key}", dependencies=WRITE)
async def put_setting(key: str, body: SettingIn, request: Request, actor: User = Depends(require("settings.write")),
                      db: AsyncSession = Depends(get_db), config: BillingConfig = Depends(billing_config)) -> SettingsOut:
    if key == "llm_models" and isinstance(body.value, dict):
        # Only models with a price, so every call stays costed (the allowlist).
        unpriced = sorted({str(v.get("model")) for v in body.value.values() if isinstance(v, dict)} - set(config.llm_prices))
        if unpriced:
            raise HTTPException(status_code=422, detail="model_not_allowed")
    try:
        return _settings_out(await runtime.write(db, actor, request, key, body.value, body.reason))
    except runtime.UnknownSetting:
        raise HTTPException(status_code=404, detail="unknown_setting") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/settings/{key}/reset", dependencies=WRITE)
async def reset_setting(key: str, body: Reason, request: Request, actor: User = Depends(require("settings.write")),
                        db: AsyncSession = Depends(get_db)) -> SettingsOut:
    try:
        return _settings_out(await runtime.reset(db, actor, request, key, body.reason))
    except runtime.UnknownSetting:
        raise HTTPException(status_code=404, detail="unknown_setting") from None


# --- audit log ---------------------------------------------------------------------------------


class AuditEntry(BaseModel):
    id: int
    actor_id: uuid.UUID | None
    actor_email: str | None
    actor_role: str
    action: str
    target_type: str | None
    target_id: str | None
    reason: str | None
    before: dict | None
    after: dict | None
    created_at: datetime


class AuditPage(BaseModel):
    entries: list[AuditEntry]
    next_before_id: int | None  # pass as before_id for the next (older) page


@router.get("/audit", dependencies=[Depends(READ_LIMIT)])
async def audit_log(
    _: User = Depends(require("audit.read")), db: AsyncSession = Depends(get_db),
    actor_id: uuid.UUID | None = None, action: str | None = Query(None, max_length=64),
    target_type: str | None = Query(None, max_length=64), target_id: str | None = Query(None, max_length=64),
    before_id: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=200),
    since: datetime | None = None, until: datetime | None = None,
) -> AuditPage:
    q = select(AdminAuditLog, User.email).outerjoin(User, User.id == AdminAuditLog.actor_id)
    if actor_id:
        q = q.where(AdminAuditLog.actor_id == actor_id)
    if action:
        q = q.where(AdminAuditLog.action == action)
    if target_type:
        q = q.where(AdminAuditLog.target_type == target_type)
    if target_id:
        q = q.where(AdminAuditLog.target_id == target_id)
    if before_id:
        q = q.where(AdminAuditLog.id < before_id)
    if since:
        q = q.where(AdminAuditLog.created_at >= since)
    if until:
        q = q.where(AdminAuditLog.created_at < until)
    rows = (await db.execute(q.order_by(AdminAuditLog.id.desc()).limit(limit + 1))).all()
    entries = [AuditEntry(id=r.id, actor_id=r.actor_id, actor_email=email, actor_role=r.actor_role,
                          action=r.action, target_type=r.target_type, target_id=r.target_id, reason=r.reason,
                          before=r.before, after=r.after, created_at=r.created_at) for r, email in rows[:limit]]
    return AuditPage(entries=entries, next_before_id=entries[-1].id if len(rows) > limit else None)


# --- staff roles -------------------------------------------------------------------------------


class StaffMember(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: Role
    last_login_at: datetime | None


@router.get("/staff", dependencies=[Depends(READ_LIMIT)])
async def staff(_: User = Depends(require("audit.read")), db: AsyncSession = Depends(get_db)) -> list[StaffMember]:
    rows = (await db.execute(select(User).where(User.role != "user", User.deleted_at.is_(None))
                             .order_by(User.role, User.email))).scalars()
    return [StaffMember(id=u.id, email=u.email, name=u.name, role=u.role, last_login_at=u.last_login_at)
            for u in rows]


class RoleIn(Reason):
    role: Role


@router.put("/users/{user_id}/role", status_code=204, dependencies=WRITE)
async def set_role(user_id: uuid.UUID, body: RoleIn, request: Request,
                   actor: User = Depends(require("roles.write")), db: AsyncSession = Depends(get_db)) -> None:
    """Promote or demote. Nobody changes their own role (no self-escalation, no lock-out),
    and the last superadmin can't be demoted."""
    if user_id == actor.id:
        raise HTTPException(status_code=409, detail="own_role")
    target = (await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None))
                               .with_for_update())).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="not_found")
    if target.role == body.role:
        return
    if target.role == "superadmin":
        # Lock every superadmin row so two concurrent demotions can't both pass the count.
        supers = (await db.execute(select(User.id).where(User.role == "superadmin", User.deleted_at.is_(None))
                                   .with_for_update())).all()
        if len(supers) <= 1:
            raise HTTPException(status_code=409, detail="last_superadmin")
    before = target.role
    target.role = body.role
    audit.record(db, actor, "roles.change", request=request, target_type="user", target_id=user_id,
                 reason=body.reason, before={"role": before}, after={"role": body.role})
    await db.commit()


# --- billing dashboard -------------------------------------------------------------------------


@billing_router.get("/overview", dependencies=[Depends(READ_LIMIT)])
async def billing_overview(days: int = Query(30, ge=1, le=365), _: User = Depends(require("billing.read")),
                           db: AsyncSession = Depends(get_db),
                           config: BillingConfig = Depends(billing_config)) -> dict[str, Any]:
    return await overview(db, config, days)


@billing_router.post("/reviews/{review_id}/resolve", status_code=204, dependencies=WRITE)
async def resolve(review_id: uuid.UUID, request: Request, actor: User = Depends(require("billing.write")),
                  db: AsyncSession = Depends(get_db)) -> None:
    review = await db.get(BillingReview, review_id)
    if review is None or review.resolved_at is not None:
        raise HTTPException(status_code=404, detail="not_found")
    audit.record(db, actor, "billing.resolve_review", request=request, target_type="billing_review",
                 target_id=review_id, before={"kind": review.kind, "resolved": False}, after={"resolved": True})
    if not await resolve_review(db, review_id):  # commits the audit row together with the change
        await db.rollback()
        raise HTTPException(status_code=404, detail="not_found")
