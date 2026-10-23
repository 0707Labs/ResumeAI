"""/app/support: the contact form. Tickets are stored (support_tickets) for the team's
inbox in /admin; a user sees only their own (row-level security too)."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.signin import per_key_limit
from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.db.models import Analysis, SupportTicket, User
from app.db.session import get_db

router = APIRouter(prefix="/api/support")
Category = Literal["support", "feedback", "fabrication_report", "grievance", "billing", "privacy"]


class TicketIn(BaseModel):
    category: Category
    subject: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=5000)
    analysis_id: uuid.UUID | None = None  # e.g. the tailoring a fabrication report is about

    @field_validator("subject", "body")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty")
        return v


class TicketOut(BaseModel):
    id: uuid.UUID
    category: Category
    subject: str
    status: Literal["open", "pending", "closed"]
    created_at: datetime
    updated_at: datetime


def _out(t: SupportTicket) -> TicketOut:
    return TicketOut(id=t.id, category=t.category, subject=t.subject, status=t.status, created_at=t.created_at,
                     updated_at=t.updated_at)


@router.post("/tickets", status_code=201,
             dependencies=[Depends(rate_limit("support_ticket", 10, 3600)), Depends(require_csrf)])
async def create_ticket(body: TicketIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> TicketOut:
    per_key_limit(f"support_user:{user.id}", 5, 3600)
    if body.analysis_id is not None and await db.scalar(
            select(Analysis.id).where(Analysis.id == body.analysis_id, Analysis.user_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="analysis_not_found")
    ticket = SupportTicket(user_id=user.id, email=user.email, category=body.category, subject=body.subject,
                           body=body.body, analysis_id=body.analysis_id)
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return _out(ticket)


@router.get("/tickets")
async def my_tickets(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[TicketOut]:
    rows = await db.scalars(select(SupportTicket).where(SupportTicket.user_id == user.id)
                            .order_by(SupportTicket.created_at.desc()).limit(50))
    return [_out(t) for t in rows]
