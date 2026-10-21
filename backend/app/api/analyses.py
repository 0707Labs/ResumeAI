"""/api/analyses: start an analysis (free; pins the resume and job description), and
the dependency the pipeline routes use to find the caller's analysis.

Signed out, or without a live analysis of your own, the pipeline still works rules-only
(no Claude calls). Claude is used only for a request whose X-Analysis-Id names the
caller's own analysis that is still usable, and whose resume and job description are
the ones pinned on it. Downloading is what pays (see /api/export in routes.py).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.auth.sessions import resolve_session
from app.billing import analyses
from app.billing.config import BillingConfig, get_billing_config
from app.billing.costs import current_analysis_id, parse_analysis_id
from app.db.models import Analysis, User
from app.db.session import get_db
from app.models import JobDescription, Resume

router = APIRouter(prefix="/api/analyses")


class StartIn(BaseModel):
    resume: Resume
    jd: JobDescription


class AnalysisOut(BaseModel):
    analysis_id: uuid.UUID
    usable_until: datetime  # Claude may be used for this analysis until then


# current_user first: a signed-out caller gets 401 (and goes rules-only) without using up
# the rate limit; the frontend calls this on every Analyze.
@router.post("", dependencies=[Depends(current_user), Depends(rate_limit("analysis_start", 10, 60)),
                               Depends(require_csrf)])
async def start(
    body: StartIn,
    idempotency_key: str | None = Header(default=None, max_length=128),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    config: BillingConfig = Depends(get_billing_config),
) -> AnalysisOut:
    """Start an analysis. Free: the first download of its tailored resume is what pays.
    Send one Idempotency-Key per Analyze click; a retry with it returns the same analysis."""
    started = await analyses.start_analysis(
        db, config, user.id, resume=body.resume.model_dump(mode="json"), jd=body.jd.model_dump(mode="json"),
        idempotency_key=idempotency_key or f"auto:{uuid.uuid4()}")
    await db.commit()
    return AnalysisOut(analysis_id=started.analysis.id, usable_until=started.analysis.usable_until)


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


def pinned_to(analysis: Analysis | None, resume: Resume, jd: JobDescription) -> Analysis | None:
    """The analysis, if this request's resume and job description are the ones it pinned."""
    if analysis is None:
        return None
    digest = analyses.inputs_digest(resume.model_dump(mode="json"), jd.model_dump(mode="json"))
    if digest != analysis.inputs_sha256:
        current_analysis_id.set(None)
        return None
    return analysis
