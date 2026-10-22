"""/api/admin/invites and /api/admin/waitlist: invite codes and the waitlist (invites.write).

Codes are 12 characters from a 32-letter alphabet without look-alikes (about 60 bits,
app.auth.invites.generate_code), stored only as a sha256 of the normalized code plus the
last four characters. They're shown once, in the response that creates them; after that
only the hint. Redemption stays atomic in sign-up (one UPDATE ... WHERE uses < max_uses),
so a code can't be used twice, past its uses, after expiry, after revocation, or by
another address when it's locked to one.

Approving a waitlist entry creates an invite bound to that address and emails it; a
failed email leaves that entry waiting. Every change is audited; codes never are.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, case, delete, exists, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.admin import audit
from app.admin.tables import csv_response
from app.api.admin import READ_LIMIT, WRITE, Reason
from app.api.signin import EMAIL_RE
from app.auth.invites import generate_code, hash_code
from app.auth.mailer import MailerError, get_mailer, waitlist_invite_mail
from app.auth.csrf import require_csrf
from app.auth.ratelimit import rate_limit
from app.auth.roles import require
from app.db.models import Analysis, Invite, InviteRedemption, User, Waitlist
from app.db.session import get_db

router = APIRouter(prefix="/api/admin")
WAITLIST_INVITE_DAYS = 30
Status = Literal["active", "exhausted", "expired", "revoked"]
Kind = Literal["admin", "personal", "waitlist"]


def _status_expr(now: datetime):
    return case(
        (Invite.revoked_at.is_not(None), "revoked"),
        (Invite.uses >= Invite.max_uses, "exhausted"),
        (and_(Invite.expires_at.is_not(None), Invite.expires_at <= now), "expired"),
        else_="active")


# --- generate ------------------------------------------------------------------------------------


class GenerateIn(BaseModel):
    count: int = Field(default=1, ge=1, le=500)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_at: datetime | None = None
    email: str | None = Field(default=None, max_length=254)  # lock a single code to this address
    bonus_credits: int | None = Field(default=None, ge=1, le=100)
    campaign: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("not an email address")
        return v


class Generated(BaseModel):
    batch_id: uuid.UUID
    codes: list[str]  # shown this once; only hashes are kept
    expires_at: datetime | None


@router.post("/invites", status_code=201,
             dependencies=[Depends(rate_limit("admin_invites_generate", 10, 3600)), Depends(require_csrf)])
async def generate(body: GenerateIn, request: Request, actor: User = Depends(require("invites.write")),
                   db: AsyncSession = Depends(get_db)) -> Generated:
    if body.email and body.count != 1:
        raise HTTPException(status_code=422, detail="email_lock_needs_one_code")
    if body.expires_at is not None and body.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="expiry_in_past")
    batch, codes = uuid.uuid4(), set()
    while len(codes) < body.count:  # unique within the batch; the hash column is unique overall
        codes.add(generate_code())
    db.add_all([Invite(code_hash=hash_code(c), code_hint=c[-4:], email=body.email, created_by=actor.id,
                       max_uses=body.max_uses, expires_at=body.expires_at, bonus_credits=body.bonus_credits,
                       campaign=body.campaign, note=body.note, kind="admin", batch_id=batch) for c in codes])
    audit.record(db, actor, "invites.generate", request=request, target_type="invite_batch", target_id=batch,
                 after={"count": body.count, "max_uses": body.max_uses, "expires_at": body.expires_at,
                        "bonus_credits": body.bonus_credits, "campaign": body.campaign, "email_locked": bool(body.email)})
    await db.commit()
    return Generated(batch_id=batch, codes=sorted(codes), expires_at=body.expires_at)


# --- list, revoke, extend, export -----------------------------------------------------------------


class InviteRow(BaseModel):
    id: uuid.UUID
    code_hint: str
    kind: Kind
    campaign: str | None
    note: str | None
    email: str | None
    uses: int
    max_uses: int
    bonus_credits: int | None
    expires_at: datetime | None
    created_at: datetime
    created_by_email: str | None
    batch_id: uuid.UUID | None
    status: Status


class InvitePage(BaseModel):
    items: list[InviteRow]
    total: int
    page: int
    page_size: int


def _invites_query(now: datetime, status: Status | None, kind: Kind | None, campaign: str | None,
                   batch_id: uuid.UUID | None, q: str | None):
    creator = aliased(User)
    st = _status_expr(now)
    stmt = select(Invite, creator.email.label("creator"), st.label("status")).outerjoin(
        creator, creator.id == Invite.created_by)
    if status:
        stmt = stmt.where(st == status)
    if kind:
        stmt = stmt.where(Invite.kind == kind)
    if campaign:
        stmt = stmt.where(Invite.campaign == campaign)
    if batch_id:
        stmt = stmt.where(Invite.batch_id == batch_id)
    if q:
        term = q.strip().upper().replace("-", "")
        stmt = stmt.where(or_(Invite.code_hint == term[-4:], Invite.email == q.strip().lower(),
                              Invite.note.ilike(f"%{q.strip()}%")))
    return stmt


def _invite_row(r) -> InviteRow:
    i = r.Invite
    return InviteRow(id=i.id, code_hint=i.code_hint, kind=i.kind, campaign=i.campaign, note=i.note, email=i.email,
                     uses=i.uses, max_uses=i.max_uses, bonus_credits=i.bonus_credits, expires_at=i.expires_at,
                     created_at=i.created_at, created_by_email=r.creator, batch_id=i.batch_id, status=r.status)


@router.get("/invites", dependencies=[Depends(READ_LIMIT)])
async def list_invites(_: User = Depends(require("invites.write")), db: AsyncSession = Depends(get_db),
                       status: Status | None = None, kind: Kind | None = None,
                       campaign: str | None = Query(None, max_length=80), batch_id: uuid.UUID | None = None,
                       q: str | None = Query(None, max_length=254), page: int = Query(1, ge=1, le=10_000),
                       page_size: int = Query(25, ge=1, le=100)) -> InvitePage:
    stmt = _invites_query(datetime.now(UTC), status, kind, campaign, batch_id, q)
    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (await db.execute(stmt.order_by(Invite.created_at.desc(), Invite.id).offset((page - 1) * page_size)
                             .limit(page_size))).all()
    return InvitePage(items=[_invite_row(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/invites/export.csv", dependencies=[Depends(READ_LIMIT)])
async def export_invites(_: User = Depends(require("invites.write")), db: AsyncSession = Depends(get_db),
                         status: Status | None = None, kind: Kind | None = None,
                         campaign: str | None = Query(None, max_length=80), batch_id: uuid.UUID | None = None) -> Response:
    """Invite metadata as CSV (hints, not codes: codes exist only at creation)."""
    rows = [_invite_row(r) for r in (await db.execute(
        _invites_query(datetime.now(UTC), status, kind, campaign, batch_id, None).order_by(Invite.created_at.desc())
        .limit(10_000))).all()]
    return csv_response(rows, InviteRow, "invites")


async def _invite(db: AsyncSession, invite_id: uuid.UUID) -> Invite:
    row = await db.scalar(select(Invite).where(Invite.id == invite_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    return row


@router.post("/invites/{invite_id}/revoke", status_code=204, dependencies=WRITE)
async def revoke(invite_id: uuid.UUID, body: Reason, request: Request, actor: User = Depends(require("invites.write")),
                 db: AsyncSession = Depends(get_db)) -> None:
    row = await _invite(db, invite_id)
    if row.revoked_at is not None:
        raise HTTPException(status_code=409, detail="already_revoked")
    if row.kind == "personal":  # through the quota function: an unused one gives the slot back
        await db.execute(text("SELECT revoke_user_invite(:u, :i)"), {"u": row.created_by, "i": row.id})
    else:
        row.revoked_at = datetime.now(UTC)
    audit.record(db, actor, "invites.revoke", request=request, target_type="invite", target_id=invite_id,
                 reason=body.reason, before={"uses": row.uses, "kind": row.kind}, after={"revoked": True})
    await db.commit()


class ExtendIn(Reason):
    expires_at: datetime


@router.post("/invites/{invite_id}/extend", status_code=204, dependencies=WRITE)
async def extend(invite_id: uuid.UUID, body: ExtendIn, request: Request, actor: User = Depends(require("invites.write")),
                 db: AsyncSession = Depends(get_db)) -> None:
    if body.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="expiry_in_past")
    row = await _invite(db, invite_id)
    if row.revoked_at is not None:
        raise HTTPException(status_code=409, detail="revoked")
    before = row.expires_at
    row.expires_at = body.expires_at
    audit.record(db, actor, "invites.extend", request=request, target_type="invite", target_id=invite_id,
                 reason=body.reason, before={"expires_at": before}, after={"expires_at": body.expires_at})
    await db.commit()


class FunnelRow(BaseModel):
    kind: Kind
    created: int
    redeemed: int
    first_tailoring: int


@router.get("/invites/funnel", dependencies=[Depends(READ_LIMIT)])
async def funnel(_: User = Depends(require("invites.write")), db: AsyncSession = Depends(get_db),
                 days: int = Query(30, ge=1, le=365)) -> list[FunnelRow]:
    """Invites created in the window, how many were redeemed, and how many of those
    people finished a first tailoring."""
    since = datetime.now(UTC) - timedelta(days=days)
    tailored = exists().where(Analysis.user_id == InviteRedemption.user_id, Analysis.tailored_at.is_not(None))
    out = []
    for kind in ("admin", "personal", "waitlist"):
        base = select(Invite.id).where(Invite.kind == kind, Invite.created_at >= since).subquery()
        created = int(await db.scalar(select(func.count()).select_from(base)) or 0)
        redeemed = int(await db.scalar(select(func.count()).select_from(InviteRedemption)
                                       .where(InviteRedemption.invite_id.in_(select(base.c.id)))) or 0)
        converted = int(await db.scalar(select(func.count()).select_from(InviteRedemption)
                                        .where(InviteRedemption.invite_id.in_(select(base.c.id)), tailored)) or 0)
        out.append(FunnelRow(kind=kind, created=created, redeemed=redeemed, first_tailoring=converted))
    return out


# --- waitlist ------------------------------------------------------------------------------------


class WaitlistRow(BaseModel):
    id: uuid.UUID
    email: str
    source: str | None
    status: Literal["waiting", "invited", "converted", "rejected"]
    created_at: datetime
    invited_at: datetime | None


class WaitlistPage(BaseModel):
    items: list[WaitlistRow]
    total: int
    page: int
    page_size: int


@router.get("/waitlist", dependencies=[Depends(READ_LIMIT)])
async def list_waitlist(_: User = Depends(require("invites.write")), db: AsyncSession = Depends(get_db),
                        status: Literal["waiting", "invited", "converted", "rejected"] | None = "waiting",
                        q: str | None = Query(None, max_length=254), page: int = Query(1, ge=1, le=10_000),
                        page_size: int = Query(50, ge=1, le=100)) -> WaitlistPage:
    stmt = select(Waitlist)
    if status:
        stmt = stmt.where(Waitlist.status == status)
    if q:
        stmt = stmt.where(Waitlist.email.ilike(f"%{q.strip().lower()}%"))
    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = await db.scalars(stmt.order_by(Waitlist.created_at, Waitlist.id).offset((page - 1) * page_size).limit(page_size))
    return WaitlistPage(items=[WaitlistRow(id=w.id, email=w.email, source=w.source, status=w.status,
                                           created_at=w.created_at, invited_at=w.invited_at) for w in rows],
                        total=total, page=page, page_size=page_size)


class IdsIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=500)


class ApproveOut(BaseModel):
    approved: int
    skipped: int  # not waiting any more (already invited, rejected, gone)
    failed: int  # the email couldn't be sent; left waiting


@router.post("/waitlist/approve", dependencies=[Depends(rate_limit("admin_waitlist", 20, 60)), Depends(require_csrf)])
async def approve(body: IdsIn, request: Request, actor: User = Depends(require("invites.write")),
                  db: AsyncSession = Depends(get_db)) -> ApproveOut:
    """Invite each waiting entry: an invite bound to their address, emailed. One at a time,
    each in its own transaction, so a failed email leaves only that entry waiting."""
    approved = skipped = failed = 0
    mailer = get_mailer()
    for entry_id in dict.fromkeys(body.ids):
        entry = await db.scalar(select(Waitlist).where(Waitlist.id == entry_id).with_for_update())
        if entry is None or entry.status != "waiting":
            skipped += 1
            await db.rollback()
            continue
        now = datetime.now(UTC)
        expires = now + timedelta(days=WAITLIST_INVITE_DAYS)
        code = generate_code()
        invite = Invite(code_hash=hash_code(code), code_hint=code[-4:], email=entry.email, created_by=actor.id,
                        max_uses=1, expires_at=expires, kind="waitlist", campaign="waitlist")
        db.add(invite)
        await db.flush()
        entry.status, entry.invite_id, entry.invited_at = "invited", invite.id, now
        audit.record(db, actor, "waitlist.approve", request=request, target_type="waitlist", target_id=entry.id,
                     reason=body.reason, after={"invite_id": invite.id, "expires_at": expires})
        try:
            await run_in_threadpool(mailer.send, waitlist_invite_mail(entry.email, f"{expires:%-d %B %Y}"))
        except MailerError:
            await db.rollback()
            failed += 1
            continue
        await db.commit()
        approved += 1
    return ApproveOut(approved=approved, skipped=skipped, failed=failed)


@router.post("/waitlist/reject", dependencies=[Depends(rate_limit("admin_waitlist", 20, 60)), Depends(require_csrf)])
async def reject(body: IdsIn, request: Request, actor: User = Depends(require("invites.write")),
                 db: AsyncSession = Depends(get_db)) -> dict:
    ids = list(dict.fromkeys(body.ids))
    done = (await db.execute(update(Waitlist).where(Waitlist.id.in_(ids), Waitlist.status == "waiting")
                             .values(status="rejected", rejected_at=func.now()).returning(Waitlist.id))).scalars().all()
    audit.record(db, actor, "waitlist.reject", request=request, target_type="waitlist",
                 target_id=str(done[0]) if len(done) == 1 else None, reason=body.reason,
                 after={"rejected": len(done), "ids": [str(i) for i in done][:50]})
    await db.commit()
    return {"rejected": len(done)}


@router.delete("/waitlist/{entry_id}", status_code=204, dependencies=WRITE)
async def delete_entry(entry_id: uuid.UUID, body: Reason, request: Request,
                       actor: User = Depends(require("invites.write")), db: AsyncSession = Depends(get_db)) -> None:
    """Remove the entry (e.g. on request). Its consent record stays, as proof it was given."""
    gone = (await db.execute(delete(Waitlist).where(Waitlist.id == entry_id).returning(Waitlist.status))).scalar_one_or_none()
    if gone is None:
        raise HTTPException(status_code=404, detail="not_found")
    audit.record(db, actor, "waitlist.delete", request=request, target_type="waitlist", target_id=entry_id,
                 reason=body.reason, before={"status": gone})
    await db.commit()
