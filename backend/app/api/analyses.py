"""/api/analyses: start an analysis (pins the resume and job description; spends nothing),
what's left of this month's free tailorings, and the dependency the pipeline routes use
to find the caller's analysis.

Signed out, or without a live analysis of your own, the pipeline still works rules-only
(no Claude calls). Claude is used only for a request whose X-Analysis-Id names the
caller's own analysis that is still usable, and whose resume and job description are
the ones pinned on it. An analysis started over the daily Claude cap is rules-only
from the start (over_daily_cap tells the pipeline why). Downloading is what pays (see
/api/downloads in routes.py).
"""

import logging
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.auth.sessions import resolve_session
from app.billing import analyses, budget
from app.admin import settings as runtime
from app.billing.config import BillingConfig
from app.billing.costs import current_analysis_id, parse_analysis_id
from app.billing.entitlements import can_start_tailoring
from app.db.models import Analysis, User
from app.db.rls import user_scope
from app.db.session import get_db
from app.models import JobDescription, Resume

log = logging.getLogger("app.billing")
router = APIRouter(prefix="/api/analyses")

# True for a request whose X-Analysis-Id names the caller's analysis that was started
# over the daily Claude cap, so the rules-only note can say so.
over_daily_cap: ContextVar[bool] = ContextVar("over_daily_cap", default=False)


class StartIn(BaseModel):
    resume: Resume
    jd: JobDescription


Uses = Literal["free", "pass", "pro", "credit"]


class AnalysisOut(BaseModel):
    analysis_id: uuid.UUID
    usable_until: datetime  # Claude may be used for this analysis until then
    uses: Uses | None  # what allowed it (nothing is spent); None on a replay
    claude: bool  # False: started over the daily Claude cap, so it runs rules-only
    claude_per_day: int  # the daily Claude cap for this user (resets 00:00 UTC)


class AllowanceOut(BaseModel):
    """What the workspace shows before Analyze: free tailorings left and what the next one uses."""

    free_allowance: int
    free_used: int
    resets_at: datetime  # start of next calendar month, UTC
    next_uses: Uses | None  # None: the pricing dialog
    credits_balance: int


# current_user first: a signed-out caller gets 401 (and goes rules-only) without using up
# the rate limit; the frontend calls this on every Analyze.
@router.post("", dependencies=[Depends(current_user), Depends(rate_limit("analysis_start", 10, 60)),
                               Depends(require_csrf)])
async def start(
    body: StartIn,
    idempotency_key: str | None = Header(default=None, max_length=128),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    config: BillingConfig = Depends(runtime.live_billing_config),
) -> AnalysisOut:
    """Start an analysis. Spends nothing (the clean download is what pays). Allowed by a
    free tailoring this month, or past those by a pass, Pro or a credit balance; 402
    no_credits otherwise. Send one Idempotency-Key per Analyze click; a retry with it
    returns the same analysis. Over the daily Claude cap it still starts (and
    downloads), with claude false."""
    # Staff paused analyses, or a Claude budget is used up with the kill switch on
    # (app.billing.budget). Running analyses finish; new ones wait for the reset.
    if (paused := await budget.pause_reason(db)) is not None:
        log.warning("analysis refused: %s", paused)
        raise HTTPException(status_code=503, detail="analyses_paused")
    try:
        started = await analyses.start_analysis(
            db, config, user.id, resume=body.resume.model_dump(mode="json"), jd=body.jd.model_dump(mode="json"),
            idempotency_key=idempotency_key or f"auto:{uuid.uuid4()}")
    except analyses.NoEntitlement as exc:
        await db.rollback()
        raise HTTPException(status_code=402, detail=exc.decision.reason) from None
    await db.commit()
    return AnalysisOut(analysis_id=started.analysis.id, usable_until=started.analysis.usable_until,
                       uses=started.decision.pays_with if started.decision else None,
                       claude=started.claude, claude_per_day=started.claude_per_day)


@router.get("/allowance")
async def allowance(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    config: BillingConfig = Depends(runtime.live_billing_config),
) -> AllowanceOut:
    now = datetime.now(UTC)
    snap = await analyses.snapshot(db, config, user.id, user.credits_balance, now)
    return AllowanceOut(free_allowance=snap.free_allowance, free_used=min(snap.free_used, snap.free_allowance),
                        resets_at=analyses.next_month_start(now), next_uses=can_start_tailoring(snap).pays_with,
                        credits_balance=snap.credits)


async def billed_analysis(request: Request, db: AsyncSession = Depends(get_db)) -> Analysis | None:
    """The caller's usable analysis named by X-Analysis-Id, or None (rules-only).
    Also tags LLM usage rows with its id; an unchecked header never reaches llm_usage.
    Without the header no database is touched, so signed-out use needs no database."""
    analysis, capped = None, False
    analysis_id = parse_analysis_id(request.headers.get("x-analysis-id"))
    if analysis_id is not None:
        signed_in = await resolve_session(db, request)
        if signed_in is not None and signed_in.user.status == "active":
            await user_scope(db, signed_in.user.id)
            analysis = await analyses.usable(db, signed_in.user.id, analysis_id)
            if analysis is None:
                capped = await db.scalar(select(Analysis.id).where(
                    Analysis.id == analysis_id, Analysis.user_id == signed_in.user.id,
                    ~analyses.WITH_CLAUDE)) is not None
    over_daily_cap.set(capped)
    # Set in the request's own context, so the sync stages run in the threadpool see it.
    current_analysis_id.set(analysis.id if analysis else None)
    return analysis


def pinned_to(analysis: Analysis | None, resume: Resume, jd: JobDescription) -> Analysis | None:
    """The analysis, if this request's resume and job description are the ones it pinned."""
    if analysis is None:
        return None
    digest = analyses.inputs_digest(resume.model_dump(mode="json"), jd.model_dump(mode="json"))
    if digest != analysis.inputs_sha256:
        current_analysis_id.set(None)
        return None
    return analysis
