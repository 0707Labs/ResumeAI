"""/api/analyses: start a tailoring (free allowance, pass, Pro or a credit balance allows
it; nothing is charged until download), what's left this month, and the dependency the
pipeline routes use to decide whether a request may call Claude.

Signed out, or without a live analysis of your own, the pipeline still works rules-only
(no Claude calls, so nothing to pay for). Claude is used only for a request whose
X-Analysis-Id names the caller's own analysis that is still usable.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.auth.sessions import resolve_session
from app.billing import analyses
from app.billing.config import BillingConfig, get_billing_config
from app.billing.entitlements import can_start_tailoring
from app.billing.costs import current_analysis_id, parse_analysis_id
from app.db.models import Analysis, User
from app.db.session import get_db

router = APIRouter(prefix="/api/analyses")


class AnalysisOut(BaseModel):
    analysis_id: uuid.UUID
    pays_with: Literal["pass", "pro", "credit", "free"]
    # Left after this run: free runs, or pass / Pro runs; for "credit", the balance. None on a replay.
    remaining: int | None
    usable_until: datetime


class AllowanceOut(BaseModel):
    """What the workspace shows before Analyze: free tailorings left and what the next one uses."""

    free_allowance: int
    free_used: int
    resets_at: datetime  # start of next calendar month, UTC
    next_uses: Literal["pass", "pro", "credit", "free"] | None  # None: the pricing dialog
    credits_balance: int


# current_user first: a signed-out caller gets 401 (and goes rules-only) without using up
# the rate limit; the frontend calls this on every Analyze.
@router.post("", dependencies=[Depends(current_user), Depends(rate_limit("analysis_start", 10, 60)),
                               Depends(require_csrf)])
async def start(
    idempotency_key: str | None = Header(default=None, max_length=128),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    config: BillingConfig = Depends(get_billing_config),
) -> AnalysisOut:
    """Start a tailoring: a free run, an active pass, Pro, or a credit balance that covers a
    download allows it, in that order. Nothing is charged. 402 no_credits when none does.
    Send one Idempotency-Key per Analyze click; a retry returns the same analysis."""
    try:
        started = await analyses.start_analysis(db, config, user.id,
                                                idempotency_key=idempotency_key or f"auto:{uuid.uuid4()}")
    except analyses.NoEntitlement as exc:
        await db.rollback()
        raise HTTPException(status_code=402, detail=exc.decision.reason) from None
    await db.commit()
    row = started.analysis
    return AnalysisOut(analysis_id=row.id, pays_with=row.entitlement,
                       remaining=started.decision.remaining if started.decision else None,
                       usable_until=row.usable_until)


@router.get("/allowance")
async def allowance(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    config: BillingConfig = Depends(get_billing_config),
) -> AllowanceOut:
    now = datetime.now(UTC)
    snap = await analyses.snapshot(db, config, user.id, user.credits_balance, now)
    month = analyses.month_start(now)
    resets = month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)
    return AllowanceOut(free_allowance=snap.free_allowance, free_used=min(snap.free_used, snap.free_allowance),
                        resets_at=resets, next_uses=can_start_tailoring(snap).pays_with,
                        credits_balance=snap.credits)


async def billed_analysis(request: Request, db: AsyncSession = Depends(get_db)) -> Analysis | None:
    """The caller's usable analysis named by X-Analysis-Id, or None (rules-only).
    Also tags LLM usage rows with its id; an unchecked header never reaches llm_usage.
    Without the header no database is touched, so signed-out use needs no database."""
    analysis = None
    analysis_id = parse_analysis_id(request.headers.get("x-analysis-id"))
    if analysis_id is not None:
        signed_in = await resolve_session(db, request)
        if signed_in is not None and signed_in.user.status == "active":
            analysis = await analyses.usable(db, signed_in.user.id, analysis_id)
    # Set in the request's own context, so the sync stages run in the threadpool see it.
    current_analysis_id.set(analysis.id if analysis else None)
    return analysis
