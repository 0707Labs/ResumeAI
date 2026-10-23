"""/api/admin/users: find a user, see their account (metadata only), and act on it.

Reads need users.read (support and up); billing details (ledger, payments) also need
billing.read. Every action is audited in its own transaction and needs a reason:
suspend / unsuspend and force sign-out (users.write), credit adjustments through the
ledger with reason admin_adjust (credits.adjust), granting a pass (passes.grant), and
deleting the account (users.delete, superadmin with a recent sign-in). Only a superadmin
acts on staff accounts; nobody acts on their own. Never resume or JD text.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import audit
from app.admin.tables import csv_response
from app.api.admin import READ_LIMIT, WRITE, Reason
from app.api.billing import billing_config
from app.auth.account import delete_account
from app.auth.roles import Role, can, require
from app.billing import ledger
from app.billing.config import BillingConfig
from app.billing.plan import plan_status
from app.db.models import (
    Account,
    AdminAuditLog,
    Analysis,
    AuthSession,
    CreditTransaction,
    Download,
    Invite,
    InviteRedemption,
    LlmUsage,
    Pass,
    Payment,
    Referral,
    Subscription,
    SupportTicket,
    User,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/admin/users")

Status = Literal["active", "suspended", "deleted"]
Plan = Literal["free", "credits", "pass", "pro"]
SORTS = ("created_at", "last_login_at", "email", "credits_balance", "tailorings", "llm_cost_usd")


# --- the list ------------------------------------------------------------------------------------


def _columns(now: datetime):
    tailorings = select(func.count()).select_from(Analysis).where(Analysis.user_id == User.id).scalar_subquery()
    downloads = select(func.count()).select_from(Download).where(Download.user_id == User.id).scalar_subquery()
    refs = select(func.count()).select_from(Referral).where(Referral.referrer_id == User.id).scalar_subquery()
    cost = (select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).select_from(LlmUsage)
            .join(Analysis, Analysis.id == LlmUsage.analysis_id).where(Analysis.user_id == User.id).scalar_subquery())
    last_seen = select(func.max(AuthSession.last_seen_at)).where(AuthSession.user_id == User.id).scalar_subquery()
    has_pass = exists().where(Pass.user_id == User.id, Pass.revoked_at.is_(None), Pass.starts_at <= now,
                              Pass.expires_at > now)
    has_pro = exists().where(Subscription.user_id == User.id, Subscription.status == "active")
    return {"tailorings": tailorings, "downloads": downloads, "referrals": refs, "llm_cost_usd": cost,
            "last_active_at": func.coalesce(last_seen, User.last_login_at), "has_pass": has_pass, "has_pro": has_pro}


class UserRow(BaseModel):
    id: uuid.UUID
    name: str | None
    email: str
    role: Role
    status: Status
    plan: Plan
    credits: int
    created_at: datetime
    last_active_at: datetime | None
    tailorings: int
    downloads: int
    referrals: int
    llm_cost_usd: float


class UserPage(BaseModel):
    items: list[UserRow]
    total: int
    page: int
    page_size: int


def _status(u: User) -> Status:
    return "deleted" if u.deleted_at is not None else u.status  # type: ignore[return-value]


def _filtered(q: str | None, status: Status | None, role: Role | None, plan: Plan | None, cols: dict):
    stmt = select(User, *[c.label(k) for k, c in cols.items()])
    if q:
        term = q.strip().lower()
        try:
            stmt = stmt.where(User.id == uuid.UUID(term))
        except ValueError:
            like = f"%{term.replace('%', '').replace('_', '')}%"
            stmt = stmt.where(or_(User.email.ilike(like), func.lower(User.name).like(like)))
    if status == "deleted":
        stmt = stmt.where(User.deleted_at.is_not(None))
    elif status:
        stmt = stmt.where(User.deleted_at.is_(None), User.status == status)
    if role:
        stmt = stmt.where(User.role == role)
    if plan == "pass":
        stmt = stmt.where(cols["has_pass"])
    elif plan == "pro":
        stmt = stmt.where(~cols["has_pass"], cols["has_pro"])
    elif plan == "credits":
        stmt = stmt.where(~cols["has_pass"], ~cols["has_pro"], User.credits_balance > 0)
    elif plan == "free":
        stmt = stmt.where(~cols["has_pass"], ~cols["has_pro"], User.credits_balance == 0)
    return stmt


def _row(r) -> UserRow:
    u = r.User
    plan: Plan = "pass" if r.has_pass else "pro" if r.has_pro else "credits" if u.credits_balance > 0 else "free"
    return UserRow(id=u.id, name=u.name, email=u.email, role=u.role, status=_status(u), plan=plan,
                   credits=u.credits_balance, created_at=u.created_at, last_active_at=r.last_active_at,
                   tailorings=r.tailorings, downloads=r.downloads, referrals=r.referrals,
                   llm_cost_usd=round(float(r.llm_cost_usd or 0), 4))


def _ordered(stmt, cols: dict, sort: str, direction: str):
    key = {"created_at": User.created_at, "last_login_at": cols["last_active_at"], "email": User.email,
           "credits_balance": User.credits_balance, "tailorings": cols["tailorings"],
           "llm_cost_usd": cols["llm_cost_usd"]}[sort]
    key = key.desc().nulls_last() if direction == "desc" else key.asc().nulls_first()
    return stmt.order_by(key, User.id)


@router.get("", dependencies=[Depends(READ_LIMIT)])
async def list_users(
    _: User = Depends(require("users.read")), db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, max_length=120), status: Status | None = None, role: Role | None = None,
    plan: Plan | None = None, sort: Literal[SORTS] = "created_at",  # type: ignore[valid-type]
    direction: Literal["asc", "desc"] = "desc", page: int = Query(1, ge=1, le=10_000),
    page_size: int = Query(25, ge=1, le=100),
) -> UserPage:
    cols = _columns(datetime.now(UTC))
    stmt = _filtered(q, status, role, plan, cols)
    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (await db.execute(_ordered(stmt, cols, sort, direction).offset((page - 1) * page_size).limit(page_size))).all()
    return UserPage(items=[_row(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/export.csv", dependencies=[Depends(READ_LIMIT)])
async def export_users(
    request: Request, actor: User = Depends(require("users.read")), db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, max_length=120), status: Status | None = None, role: Role | None = None,
    plan: Plan | None = None, sort: Literal[SORTS] = "created_at",  # type: ignore[valid-type]
    direction: Literal["asc", "desc"] = "desc",
) -> Response:
    """The filtered list as CSV (at most 10,000 rows). Audited: it's a bulk copy of emails."""
    cols = _columns(datetime.now(UTC))
    rows = [_row(r) for r in (await db.execute(_ordered(_filtered(q, status, role, plan, cols), cols, sort, direction)
                                               .limit(10_000))).all()]
    audit.record(db, actor, "users.export", request=request, target_type="users",
                 after={"rows": len(rows), "filters": {"q": bool(q), "status": status, "role": role, "plan": plan}})
    await db.commit()
    return csv_response(rows, UserRow, "users")


# --- one user ------------------------------------------------------------------------------------


class UserDetail(BaseModel):
    user: UserRow
    phone: str | None
    onboarded: bool
    providers: list[dict[str, Any]]
    plan: dict[str, Any] | None  # None without billing.read
    ledger: list[dict[str, Any]] | None
    payments: list[dict[str, Any]] | None
    tailorings: list[dict[str, Any]]
    downloads: list[dict[str, Any]]
    invites_sent: list[dict[str, Any]]
    invited_with: dict[str, Any] | None
    referrals: list[dict[str, Any]]
    referred_by: dict[str, Any] | None
    tickets: list[dict[str, Any]]
    audit: list[dict[str, Any]]
    can: dict[str, bool]  # what the caller may do to this account


async def _target(db: AsyncSession, user_id: uuid.UUID, *, lock: bool = False) -> User:
    q = select(User).where(User.id == user_id)
    target = await db.scalar(q.with_for_update() if lock else q)
    if target is None:
        raise HTTPException(status_code=404, detail="not_found")
    return target


def _may_act(actor: User, target: User) -> bool:
    """Not on yourself; only a superadmin on staff accounts."""
    return actor.id != target.id and (target.role == "user" or actor.role == "superadmin")


@router.get("/{user_id}", dependencies=[Depends(READ_LIMIT)])
async def user_detail(user_id: uuid.UUID, actor: User = Depends(require("users.read")),
                      db: AsyncSession = Depends(get_db),
                      config: BillingConfig = Depends(billing_config)) -> UserDetail:
    now = datetime.now(UTC)
    cols = _columns(now)
    row = (await db.execute(_filtered(None, None, None, None, cols).where(User.id == user_id))).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    target: User = row.User
    billing = can(actor.role, "billing.read")

    providers = [{"provider": a.provider, "email": a.email_at_link, "linked_at": a.created_at}
                 for a in await db.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.created_at))]
    downloaded = exists().where(Download.analysis_id == Analysis.id)
    cost = (select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(LlmUsage.analysis_id == Analysis.id)
            .scalar_subquery())
    tailorings = [
        {"id": a.id, "created_at": a.created_at, "job_title": a.job_title, "company": a.company,
         "ats_before": float(a.ats_before) if a.ats_before is not None else None,
         "ats_after": float(a.ats_after) if a.ats_after is not None else None,
         "status": "downloaded" if d else "tailored" if a.tailored_at else "started", "llm_tailored": a.llm_tailored,
         "purged": a.purged_at is not None, "deleted": a.deleted_at is not None, "llm_cost_usd": round(float(c or 0), 4)}
        for a, d, c in (await db.execute(select(Analysis, downloaded, cost).where(Analysis.user_id == user_id)
                                         .order_by(Analysis.created_at.desc()).limit(50))).all()]
    downloads = [{"id": d.id, "analysis_id": d.analysis_id, "format": d.format, "paid_with": d.paid_with,
                  "credits": d.credits, "created_at": d.created_at, "file_kept": d.final_resume is not None}
                 for d in await db.scalars(select(Download).where(Download.user_id == user_id)
                                           .order_by(Download.created_at.desc()).limit(50))]
    invites_sent = [{"id": i.id, "email": i.email, "uses": i.uses, "created_at": i.created_at,
                     "expires_at": i.expires_at, "revoked_at": i.revoked_at}
                    for i in await db.scalars(select(Invite).where(Invite.created_by == user_id, Invite.kind == "personal")
                                              .order_by(Invite.created_at.desc()).limit(50))]
    used = (await db.execute(select(Invite, InviteRedemption.redeemed_at).join(
        InviteRedemption, InviteRedemption.invite_id == Invite.id).where(InviteRedemption.user_id == user_id))).first()
    invited_with = None if used is None else {
        "invite_id": used.Invite.id, "kind": used.Invite.kind, "code_hint": used.Invite.code_hint,
        "campaign": used.Invite.campaign, "created_by": used.Invite.created_by, "redeemed_at": used.redeemed_at}
    referee = select(User.email).where(User.id == Referral.referee_id).scalar_subquery()
    referrals = [{"id": r.id, "referee_email": e, "status": r.status, "reason": r.reason, "needs_review": r.needs_review,
                  "reward_credits": r.reward_credits, "created_at": r.created_at}
                 for r, e in (await db.execute(select(Referral, referee).where(Referral.referrer_id == user_id)
                                               .order_by(Referral.created_at.desc()).limit(50))).all()]
    by = (await db.execute(select(Referral, User.email).join(User, User.id == Referral.referrer_id)
                           .where(Referral.referee_id == user_id))).first()
    referred_by = None if by is None else {"referral_id": by.Referral.id, "referrer_id": by.Referral.referrer_id,
                                           "referrer_email": by.email, "status": by.Referral.status}
    tickets = [{"id": t.id, "category": t.category, "subject": t.subject, "status": t.status, "created_at": t.created_at}
               for t in await db.scalars(select(SupportTicket).where(SupportTicket.user_id == user_id)
                                         .order_by(SupportTicket.created_at.desc()).limit(50))]
    trail = [{"id": a.id, "action": a.action, "actor_id": a.actor_id, "actor_role": a.actor_role, "reason": a.reason,
              "before": a.before, "after": a.after, "created_at": a.created_at}
             for a in await db.scalars(select(AdminAuditLog).where(
                 AdminAuditLog.target_type == "user", AdminAuditLog.target_id == str(user_id))
                 .order_by(AdminAuditLog.id.desc()).limit(50))] if can(actor.role, "audit.read") else []

    plan = ledger_rows = payments = None
    if billing:
        plan = (await plan_status(db, config, target, now)).__dict__
        ledger_rows = [{"id": t.id, "delta": t.delta, "reason": t.reason, "balance_after": t.balance_after,
                        "note": t.note, "created_at": t.created_at}
                       for t in await db.scalars(select(CreditTransaction).where(CreditTransaction.user_id == user_id)
                                                 .order_by(CreditTransaction.id.desc()).limit(50))]
        payments = [{"id": p.id, "product_key": p.product_key, "status": p.status, "amount_minor": p.amount_minor,
                     "currency": p.currency, "provider_payment_id": p.provider_payment_id, "created_at": p.created_at,
                     "paid_at": p.paid_at}
                    for p in await db.scalars(select(Payment).where(Payment.user_id == user_id)
                                              .order_by(Payment.created_at.desc()).limit(50))]
    acting = _may_act(actor, target) and target.deleted_at is None
    return UserDetail(
        user=_row(row), phone=target.phone, onboarded=target.onboarded_at is not None, providers=providers,
        plan=plan, ledger=ledger_rows, payments=payments, tailorings=tailorings, downloads=downloads,
        invites_sent=invites_sent, invited_with=invited_with, referrals=referrals, referred_by=referred_by,
        tickets=tickets, audit=trail,
        can={cap.replace(".", "_"): acting and can(actor.role, cap)
             for cap in ("users.write", "credits.adjust", "passes.grant", "users.delete")})


# --- actions -------------------------------------------------------------------------------------


async def _actionable(db: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    target = await _target(db, user_id, lock=True)
    if target.deleted_at is not None:
        raise HTTPException(status_code=409, detail="deleted")
    if not _may_act(actor, target):
        raise HTTPException(status_code=403, detail="forbidden")
    return target


@router.post("/{user_id}/suspend", status_code=204, dependencies=WRITE)
async def suspend(user_id: uuid.UUID, body: Reason, request: Request, actor: User = Depends(require("users.write")),
                  db: AsyncSession = Depends(get_db)) -> None:
    """Suspend: every session ends and sign-in is refused until unsuspended."""
    target = await _actionable(db, actor, user_id)
    before = target.status
    target.status = "suspended"
    ended = (await db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))).rowcount
    audit.record(db, actor, "users.suspend", request=request, target_type="user", target_id=user_id,
                 reason=body.reason, before={"status": before}, after={"status": "suspended", "sessions_ended": ended})
    await db.commit()


@router.post("/{user_id}/unsuspend", status_code=204, dependencies=WRITE)
async def unsuspend(user_id: uuid.UUID, body: Reason, request: Request, actor: User = Depends(require("users.write")),
                    db: AsyncSession = Depends(get_db)) -> None:
    target = await _actionable(db, actor, user_id)
    before = target.status
    target.status = "active"
    audit.record(db, actor, "users.unsuspend", request=request, target_type="user", target_id=user_id,
                 reason=body.reason, before={"status": before}, after={"status": "active"})
    await db.commit()


@router.post("/{user_id}/sign-out", status_code=204, dependencies=WRITE)
async def force_sign_out(user_id: uuid.UUID, body: Reason, request: Request,
                         actor: User = Depends(require("users.write")), db: AsyncSession = Depends(get_db)) -> None:
    await _actionable(db, actor, user_id)
    ended = (await db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))).rowcount
    audit.record(db, actor, "users.sign_out", request=request, target_type="user", target_id=user_id,
                 reason=body.reason, after={"sessions_ended": ended})
    await db.commit()


class CreditsIn(Reason):
    delta: int = Field(ge=-1000, le=1000)


@router.post("/{user_id}/credits", dependencies=WRITE)
async def adjust_credits(user_id: uuid.UUID, body: CreditsIn, request: Request,
                         actor: User = Depends(require("credits.adjust")), db: AsyncSession = Depends(get_db)) -> dict:
    """Add or remove credits through the ledger (reason admin_adjust). Never below zero."""
    if body.delta == 0:
        raise HTTPException(status_code=422, detail="delta_zero")
    target = await _actionable(db, actor, user_id)
    before = target.credits_balance
    key = f"admin:{uuid.uuid4()}"
    try:
        posted = await ledger.post(db, user_id, body.delta, reason="admin_adjust", idempotency_key=key,
                                   note=body.reason[:200])
    except ledger.InsufficientCredits:
        await db.rollback()
        raise HTTPException(status_code=409, detail="insufficient_credits") from None
    audit.record(db, actor, "credits.adjust", request=request, target_type="user", target_id=user_id,
                 reason=body.reason, before={"balance": before},
                 after={"balance": posted.balance, "delta": body.delta, "ledger_key": key})
    await db.commit()
    return {"credits_balance": posted.balance}


class PassIn(Reason):
    days: int | None = Field(default=None, ge=1, le=365)


@router.post("/{user_id}/pass", dependencies=WRITE)
async def grant_pass(user_id: uuid.UUID, body: PassIn, request: Request, actor: User = Depends(require("passes.grant")),
                     db: AsyncSession = Depends(get_db), config: BillingConfig = Depends(billing_config)) -> dict:
    """Grant a Job Hunt Pass (the configured pass product; its length unless days is given)."""
    product = next((p for p in config.products.values() if p.kind == "pass"), None)
    if product is None:
        raise HTTPException(status_code=409, detail="no_pass_product")
    await _actionable(db, actor, user_id)
    days, ref = body.days or product.pass_days, f"admin:{uuid.uuid4()}"
    grant = await ledger.grant_pass(db, user_id, product_key=product.key, days=days,
                                    analyses_cap=product.fair_use_cap, reference_id=ref)
    audit.record(db, actor, "passes.grant", request=request, target_type="user", target_id=user_id,
                 reason=body.reason, after={"pass_id": grant.pass_id, "days": days, "starts_at": grant.starts_at,
                                            "expires_at": grant.expires_at, "reference": ref})
    await db.commit()
    return {"pass_id": grant.pass_id, "starts_at": grant.starts_at, "expires_at": grant.expires_at}


@router.delete("/{user_id}", status_code=204, dependencies=WRITE)
async def delete_user(user_id: uuid.UUID, body: Reason, request: Request,
                      actor: User = Depends(require("users.delete")), db: AsyncSession = Depends(get_db)) -> None:
    """The account-deletion flow users run themselves: login methods, sessions, saved
    resumes, preferences and picture go now; tailoring text follows the retention purge."""
    target = await _actionable(db, actor, user_id)
    audit.record(db, actor, "users.delete", request=request, target_type="user", target_id=user_id,
                 reason=body.reason, before={"status": target.status, "role": target.role})
    await delete_account(db, target)  # commits, with the audit row
