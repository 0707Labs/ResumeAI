"""/api/admin/support: the inbox for the contact form (tickets.read / tickets.write; support
and up). Staff reply by email (the reply is stored and sent to the account's address;
the ticket then waits on the user), leave internal notes the user never sees, assign a
ticket to a staff member and change its status. Every change is audited; message text
stays out of the audit log.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.admin import audit
from app.api.admin import READ_LIMIT, WRITE
from app.auth.mailer import MailerError, get_mailer, ticket_reply_mail
from app.auth.roles import STAFF, can, require
from app.db.models import SupportTicket, SupportTicketMessage, User
from app.db.session import get_db

router = APIRouter(prefix="/api/admin/support")
Status = Literal["open", "pending", "closed"]
Category = Literal["support", "feedback", "fabrication_report", "grievance", "billing", "privacy"]


class TicketRow(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    email: str
    category: Category
    subject: str
    status: Status
    assignee_id: uuid.UUID | None
    assignee_email: str | None
    analysis_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TicketPage(BaseModel):
    items: list[TicketRow]
    total: int
    page: int
    page_size: int


def _row(t: SupportTicket, assignee: str | None) -> TicketRow:
    return TicketRow(id=t.id, user_id=t.user_id, email=t.email, category=t.category, subject=t.subject, status=t.status,
                     assignee_id=t.assignee_id, assignee_email=assignee, analysis_id=t.analysis_id,
                     created_at=t.created_at, updated_at=t.updated_at)


@router.get("", dependencies=[Depends(READ_LIMIT)])
async def inbox(me: User = Depends(require("tickets.read")), db: AsyncSession = Depends(get_db),
                status: Status | Literal["active"] | None = "active", category: Category | None = None,
                assignee: Literal["me", "none"] | None = None, q: str | None = Query(None, max_length=200),
                page: int = Query(1, ge=1, le=10_000), page_size: int = Query(25, ge=1, le=100)) -> TicketPage:
    """Oldest waiting first. status=active means open or pending."""
    staff = aliased(User)
    stmt = select(SupportTicket, staff.email).outerjoin(staff, staff.id == SupportTicket.assignee_id)
    if status == "active":
        stmt = stmt.where(SupportTicket.status != "closed")
    elif status:
        stmt = stmt.where(SupportTicket.status == status)
    if category:
        stmt = stmt.where(SupportTicket.category == category)
    if assignee == "me":
        stmt = stmt.where(SupportTicket.assignee_id == me.id)
    elif assignee == "none":
        stmt = stmt.where(SupportTicket.assignee_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(SupportTicket.subject.ilike(like), SupportTicket.email.ilike(like)))
    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (await db.execute(stmt.order_by(SupportTicket.status == "closed", SupportTicket.updated_at, SupportTicket.id)
                             .offset((page - 1) * page_size).limit(page_size))).all()
    return TicketPage(items=[_row(t, e) for t, e in rows], total=total, page=page, page_size=page_size)


class Message(BaseModel):
    id: uuid.UUID
    kind: Literal["reply", "internal_note"]
    body: str
    author_email: str | None
    emailed_at: datetime | None
    created_at: datetime


class TicketDetail(TicketRow):
    body: str
    messages: list[Message]
    staff: list[dict]  # who it can be assigned to


async def _ticket(db: AsyncSession, ticket_id: uuid.UUID, *, lock: bool = False) -> SupportTicket:
    q = select(SupportTicket).where(SupportTicket.id == ticket_id)
    row = await db.scalar(q.with_for_update() if lock else q)
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    return row


@router.get("/{ticket_id}", dependencies=[Depends(READ_LIMIT)])
async def ticket(ticket_id: uuid.UUID, _: User = Depends(require("tickets.read")),
                 db: AsyncSession = Depends(get_db)) -> TicketDetail:
    t = await _ticket(db, ticket_id)
    author = aliased(User)
    msgs = [Message(id=m.id, kind=m.kind, body=m.body, author_email=e, emailed_at=m.emailed_at, created_at=m.created_at)
            for m, e in (await db.execute(select(SupportTicketMessage, author.email)
                                          .outerjoin(author, author.id == SupportTicketMessage.author_id)
                                          .where(SupportTicketMessage.ticket_id == t.id)
                                          .order_by(SupportTicketMessage.created_at))).all()]
    assignee = await db.scalar(select(User.email).where(User.id == t.assignee_id)) if t.assignee_id else None
    staff = [{"id": u.id, "email": u.email, "role": u.role} for u in await db.scalars(
        select(User).where(User.role.in_(STAFF), User.deleted_at.is_(None), User.status == "active").order_by(User.email))
        if can(u.role, "tickets.write")]
    return TicketDetail(**_row(t, assignee).model_dump(), body=t.body, messages=msgs, staff=staff)


class BodyIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty")
        return v


@router.post("/{ticket_id}/reply", status_code=201, dependencies=WRITE)
async def reply(ticket_id: uuid.UUID, body: BodyIn, request: Request, actor: User = Depends(require("tickets.write")),
                db: AsyncSession = Depends(get_db)) -> Message:
    """Email the reply to the ticket's address and keep it on the ticket. Nothing is kept
    if the email can't be sent (503 email_unavailable)."""
    t = await _ticket(db, ticket_id, lock=True)
    now = datetime.now(UTC)
    msg = SupportTicketMessage(ticket_id=t.id, author_id=actor.id, kind="reply", body=body.body, emailed_at=now)
    db.add(msg)
    before = t.status
    t.status, t.updated_at = "pending", now
    if t.assignee_id is None:
        t.assignee_id = actor.id
    audit.record(db, actor, "tickets.reply", request=request, target_type="ticket", target_id=t.id,
                 before={"status": before}, after={"status": "pending", "length": len(body.body)})
    try:
        await run_in_threadpool(get_mailer().send, ticket_reply_mail(t.email, t.subject, body.body))
    except MailerError:
        await db.rollback()
        raise HTTPException(status_code=503, detail="email_unavailable") from None
    await db.commit()
    await db.refresh(msg)
    return Message(id=msg.id, kind="reply", body=msg.body, author_email=actor.email, emailed_at=msg.emailed_at,
                   created_at=msg.created_at)


@router.post("/{ticket_id}/note", status_code=201, dependencies=WRITE)
async def note(ticket_id: uuid.UUID, body: BodyIn, request: Request, actor: User = Depends(require("tickets.write")),
               db: AsyncSession = Depends(get_db)) -> Message:
    """An internal note: for staff only, never emailed or shown to the user."""
    t = await _ticket(db, ticket_id, lock=True)
    msg = SupportTicketMessage(ticket_id=t.id, author_id=actor.id, kind="internal_note", body=body.body)
    db.add(msg)
    t.updated_at = datetime.now(UTC)
    audit.record(db, actor, "tickets.note", request=request, target_type="ticket", target_id=t.id,
                 after={"length": len(body.body)})
    await db.commit()
    await db.refresh(msg)
    return Message(id=msg.id, kind="internal_note", body=msg.body, author_email=actor.email, emailed_at=None,
                   created_at=msg.created_at)


class TicketPatch(BaseModel):
    status: Status | None = None
    assignee_id: uuid.UUID | None = None
    unassign: bool = False


@router.patch("/{ticket_id}", dependencies=WRITE)
async def update_ticket(ticket_id: uuid.UUID, body: TicketPatch, request: Request,
                        actor: User = Depends(require("tickets.write")), db: AsyncSession = Depends(get_db)) -> TicketRow:
    t = await _ticket(db, ticket_id, lock=True)
    before = {"status": t.status, "assignee_id": t.assignee_id}
    if body.status:
        t.status = body.status
    if body.unassign:
        t.assignee_id = None
    elif body.assignee_id:
        staff = await db.scalar(select(User).where(User.id == body.assignee_id, User.deleted_at.is_(None)))
        if staff is None or not can(staff.role, "tickets.write"):
            raise HTTPException(status_code=422, detail="not_staff")
        t.assignee_id = staff.id
    t.updated_at = datetime.now(UTC)
    audit.record(db, actor, "tickets.update", request=request, target_type="ticket", target_id=t.id,
                 before=before, after={"status": t.status, "assignee_id": t.assignee_id})
    await db.commit()
    assignee = await db.scalar(select(User.email).where(User.id == t.assignee_id)) if t.assignee_id else None
    return _row(t, assignee)
