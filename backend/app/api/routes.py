import re
from pathlib import Path
from typing import Literal

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Header, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis import AnswerError, analyze, apply_answers, refine_with_llm
from app.api.analyses import billed_analysis, pinned_to
from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.auth.signing import sign, unsign
from app.billing import analyses
from app.billing.config import BillingConfig, get_billing_config
from app.billing.costs import parse_analysis_id
from app.config import get_settings
from app.db.models import Analysis, Download, User
from app.db.session import get_db
from app.export.preview import render_preview
from app.export.render import to_docx, to_pdf
from app.llm.client import LLM, get_llm
from app.mentor import build_advice, polish
from app.models import (
    WEIGHTS,
    ATSReport,
    AnswerIn,
    GapAnalysis,
    JobDescription,
    MentorAdvice,
    Resume,
    TailoredBullet,
    TailoredResume,
    VerificationResult,
)
from app.parsing.synonyms import skill_synonyms
from app.scoring import score
from app.tailoring import apply_tailoring, tailor, verify_bullet, verify_summary
from app.tailoring.tailor import RULES_FALLBACK
from app.parsing import (
    MAX_BYTES,
    ExtractionError,
    UnsupportedFileType,
    parse_jd,
    parse_resume_file,
)

router = APIRouter()

NO_KEY = "Rules only (no ANTHROPIC_API_KEY set)."
NO_ANALYSIS = "Rules only (sign in and start an analysis to use Claude)."


def claude_for(use_llm: bool, analysis: Analysis | None) -> tuple[LLM | None, str | None]:
    """Claude only for the caller's own live analysis, with this request's resume and
    job description pinned on it (see pinned_to); otherwise rules-only, with a note
    saying why (None when the caller asked for rules only)."""
    if not use_llm:
        return None, None
    llm = get_llm()
    if llm is None:
        return None, NO_KEY
    if analysis is None:
        return None, NO_ANALYSIS
    return llm, None


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_configured": get_settings().llm_configured}


@router.get("/api/ats/weights")
def ats_weights() -> dict[str, float]:
    return {c.value: w for c, w in WEIGHTS.items()}


@router.post("/api/resume/parse")
async def parse_resume(file: UploadFile = File(...)) -> Resume:
    data = await file.read(MAX_BYTES + 1)
    try:
        return parse_resume_file(data, file.filename or "")
    except ExtractionError as exc:
        if len(data) > MAX_BYTES:
            status = 413
        elif isinstance(exc, UnsupportedFileType):
            status = 415
        else:
            status = 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


class JDInput(BaseModel):
    text: str = Field(min_length=20, max_length=50_000)


@router.post("/api/jd/parse")
def parse_job_description(body: JDInput) -> JobDescription:
    return parse_jd(body.text)


class GapRequest(BaseModel):
    resume: Resume
    jd: JobDescription
    use_llm: bool = True


@router.post("/api/gap/analyze")
def gap_analyze(body: GapRequest, billed: Analysis | None = Depends(billed_analysis)) -> GapAnalysis:
    analysis = analyze(body.resume, body.jd)
    llm, why = claude_for(body.use_llm, pinned_to(billed, body.resume, body.jd))
    if llm is None:
        return analysis.model_copy(update={"notes": [why or "Rules only."]})
    analysis, note = refine_with_llm(analysis, body.resume, llm)
    return analysis.model_copy(update={"notes": [note]})


class AnswersRequest(BaseModel):
    analysis: GapAnalysis
    # Plain text, or {"choice": "yes"|"no"|"skip", "text": "..."} from the UI.
    answers: dict[str, AnswerIn | str]


@router.post("/api/gap/answers")
def gap_answers(body: AnswersRequest) -> GapAnalysis:
    try:
        return apply_answers(body.analysis, body.answers)
    except AnswerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class TailorRequest(BaseModel):
    resume: Resume
    jd: JobDescription
    analysis: GapAnalysis | None = None  # include it so confirmed answers can be used
    use_llm: bool = True


@router.post("/api/tailor")
async def tailor_resume(body: TailorRequest, billed: Analysis | None = Depends(billed_analysis),
                        db: AsyncSession = Depends(get_db)) -> TailoredResume:
    """Free. For a signed-in analysis Claude tailors once (a repeat is rules-only), and
    the first result is kept on the analysis."""
    billed = pinned_to(billed, body.resume, body.jd)
    if billed is not None and billed.tailored is not None:
        billed = None
    llm, why = claude_for(body.use_llm, billed)
    result = await run_in_threadpool(tailor, body.resume, body.jd, body.analysis, llm)
    if why:
        result.notes.insert(0, why)
    if billed is not None:
        billed.tailored = result.model_dump(mode="json")
        billed.llm_tailored = llm is not None and not any(n.startswith(RULES_FALLBACK) for n in result.notes)
        billed.tailored_at = func.now()
        await db.commit()
    return result


class VerifyRequest(BaseModel):
    resume: Resume
    bullets: list[TailoredBullet]
    analysis: GapAnalysis | None = None
    jd_text: str = ""
    summary: str | None = None


class VerifyResponse(BaseModel):
    bullets: list[TailoredBullet]
    summary_verification: VerificationResult | None = None


@router.post("/api/verify")
def verify(body: VerifyRequest) -> VerifyResponse:
    """Re-check bullets after the user edits them in the UI. Any verification
    sent by the client is discarded and recomputed."""
    bullets = [b.model_copy(update={"verification": verify_bullet(
        b, body.resume, body.analysis, body.jd_text)}) for b in body.bullets]
    summary = (verify_summary(body.summary, body.resume, body.analysis, body.jd_text)
               if body.summary else None)
    return VerifyResponse(bullets=bullets, summary_verification=summary)


def reverify(tailored: TailoredResume, resume: Resume, analysis: GapAnalysis | None,
             jd_text: str) -> TailoredResume:
    """Recompute every verification server-side; what the client sent is ignored."""
    checked = tailored.model_copy(update={"bullets": [
        b.model_copy(update={"verification": verify_bullet(b, resume, analysis, jd_text)})
        for b in tailored.bullets]})
    if checked.summary:
        checked = checked.model_copy(update={"summary_verification": verify_summary(
            checked.summary, resume, analysis, jd_text)})
    return checked


@router.get("/api/ats/synonyms")
def ats_synonyms() -> dict[str, list[str]]:
    """Terms the scorer treats as the same skill, e.g. javascript: [JS, ES6, ...]."""
    return skill_synonyms()


class ScoreRequest(BaseModel):
    resume: Resume
    jd: JobDescription
    tailored: TailoredResume | None = None
    analysis: GapAnalysis | None = None  # needed for bullets backed by confirmed answers
    use_llm: bool = True
    # True: "after" counts only bullets the user approved (what export will use).
    # False: every verified bullet not rejected (a preview of the full tailoring).
    approved_only: bool = False


class ScoreResponse(BaseModel):
    before: ATSReport
    after: ATSReport | None = None
    delta: float | None = None


@router.post("/api/ats/score")
def ats_score(body: ScoreRequest, billed: Analysis | None = Depends(billed_analysis)) -> ScoreResponse:
    llm, _ = claude_for(body.use_llm, pinned_to(billed, body.resume, body.jd))
    before = score(body.resume, body.jd, llm=llm)
    if body.tailored is None:
        return ScoreResponse(before=before)
    checked = reverify(body.tailored, body.resume, body.analysis, body.jd.raw_text)
    after = score(apply_tailoring(body.resume, checked, approved_only=body.approved_only),
                  body.jd, llm=llm)
    return ScoreResponse(before=before, after=after, delta=round(after.total - before.total, 1))


class MentorRequest(BaseModel):
    resume: Resume
    jd: JobDescription
    analysis: GapAnalysis | None = None  # computed (rules only) if omitted
    ats: ATSReport | None = None  # computed (rules only) if omitted
    use_llm: bool = True


@router.post("/api/mentor")
def mentor(body: MentorRequest, billed: Analysis | None = Depends(billed_analysis)) -> MentorAdvice:
    analysis = body.analysis or analyze(body.resume, body.jd)
    ats = body.ats or score(body.resume, body.jd)
    advice = build_advice(body.resume, body.jd, analysis, ats)
    llm, _ = claude_for(body.use_llm, pinned_to(billed, body.resume, body.jd))
    return polish(advice, llm) if llm is not None else advice


_SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@router.get("/api/sample")
def sample() -> dict[str, str]:
    """A demo resume and JD, so the UI can be tried without uploading anything."""
    return {"resume_text": (_SAMPLES / "resume.txt").read_text(),
            "jd_text": (_SAMPLES / "jd.txt").read_text()}


class ExportRequest(BaseModel):
    resume: Resume
    tailored: TailoredResume
    analysis: GapAnalysis | None = None
    jd_text: str = ""


_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


class PreviewIn(ExportRequest):
    mark_changes: bool = True  # tint the changed lines on the images


class PreviewPageOut(BaseModel):
    image: str  # data:image/png;base64,... (low resolution, watermarked, partly masked)
    width: int
    height: int


class PreviewResponse(BaseModel):
    """The download, before paying for it: page images only, never its text."""

    pages: list[PreviewPageOut]
    masked: list[str]  # what's blurred, in words ("contact details", "the Skills section")
    changed_count: int  # final lines that differ from the original resume
    changed_marked: int  # of those, lines tinted on the images


@router.post("/api/export/preview", dependencies=[Depends(rate_limit("preview", 30, 60))])
async def export_preview(body: PreviewIn) -> PreviewResponse:
    """What the download will contain, after the same server-side checks, rendered on the
    server as low-resolution PNGs with a diagonal watermark and the contact details and
    last section blurred. No text of the resume is sent back."""
    final = _final(body.resume, body.tailored, body.analysis, body.jd_text)
    original = {b.text for b in body.resume.bullets()}
    changed = [b.text for b in final.bullets() if b.text not in original]
    if final.summary and final.summary != body.resume.summary:
        changed.append(final.summary)
    shown = await run_in_threadpool(render_preview, final, changed, mark_changes=body.mark_changes)
    return PreviewResponse(pages=[PreviewPageOut(image=p.data_url(), width=p.width, height=p.height) for p in shown.pages],
                           masked=shown.masked, changed_count=len(changed), changed_marked=shown.changed_marked)


def _final(resume: Resume, tailored: TailoredResume, analysis: GapAnalysis | None, jd_text: str) -> Resume:
    """What a download contains: bullets that pass verification now AND were approved
    by the user use tailored text; everything else keeps its original wording."""
    return apply_tailoring(resume, reverify(tailored, resume, analysis, jd_text), approved_only=True)


def _render(fmt: str, final: Resume, mark: str | None = None) -> tuple[bytes, str]:
    data = to_docx(final, mark=mark) if fmt == "docx" else to_pdf(final, mark=mark)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", final.name or "resume").strip("_") or "resume"
    return data, f"{stem}_tailored.{fmt}"


class DownloadLink(BaseModel):
    url: str  # same-origin, signed, single user; GET it to receive the file
    expires_at: datetime
    paid_with: Literal["pass", "pro", "credit", "window"]
    credits_balance: int


_LINK = "download"


def download_ref(download_id: uuid.UUID) -> str:
    """The identifier written into a downloaded file's metadata."""
    return f"rt-dl-{download_id.hex}"


@router.post("/api/downloads/{fmt}", dependencies=[Depends(rate_limit("download", 20, 60)), Depends(require_csrf)])
async def request_download(
    fmt: Literal["docx", "pdf"],
    body: ExportRequest,
    x_analysis_id: str | None = Header(default=None),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    config: BillingConfig = Depends(get_billing_config),
) -> DownloadLink:
    """Pay for a clean download and get a short-lived signed link to it. Needs sign-in
    and the analysis (X-Analysis-Id); the file is built from the resume and job
    description pinned on it (body.resume and body.jd_text are ignored). Nothing is
    rendered before the entitlement check passes: a paid download of the same analysis
    within the re-download window covers it, else a pass, Pro or a credit pays (402
    no_credits when none can). The check render shares the charge's transaction, so a
    failed export charges nothing."""
    analysis_id = parse_analysis_id(x_analysis_id)
    if analysis_id is None:
        raise HTTPException(status_code=409, detail="analysis_required")
    try:
        row = await analyses.owned(db, user.id, analysis_id)
    except analyses.UnknownAnalysis:
        raise HTTPException(status_code=404, detail="analysis_not_found") from None
    final = _final(Resume.model_validate(row.resume), body.tailored, body.analysis, row.jd.get("raw_text", ""))
    try:
        paid = await analyses.pay_for_download(db, config, user.id, analysis_id, fmt=fmt,
                                               final_resume=final.model_dump(mode="json"))
    except analyses.NoEntitlement as exc:
        await db.rollback()
        raise HTTPException(status_code=402, detail=exc.decision.reason) from None
    try:
        await run_in_threadpool(_render, fmt, final)  # entitlement passed; prove it renders before charging
    except Exception:
        await db.rollback()
        raise
    download = paid.download
    await db.commit()
    expires = datetime.now(UTC) + timedelta(seconds=config.downloads.url_ttl_seconds)
    token = sign(_LINK, f"{download.id}:{int(expires.timestamp())}")
    balance = await db.scalar(select(User.credits_balance).where(User.id == user.id))
    return DownloadLink(url=f"/api/downloads/file/{token}", expires_at=expires, paid_with=download.paid_with,
                        credits_balance=balance or 0)


@router.get("/api/downloads/file/{token}")
async def download_file(token: str, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)) -> Response:
    """The file behind a signed link: only for the user who paid, only until it expires."""
    value = unsign(_LINK, token)
    try:
        download_id, expires = value.split(":") if value else ("", "0")
        download_id, expires = uuid.UUID(download_id), int(expires)
    except ValueError:
        raise HTTPException(status_code=404, detail="link_invalid") from None
    if datetime.now(UTC).timestamp() > expires:
        raise HTTPException(status_code=410, detail="link_expired")
    row = await db.scalar(select(Download).where(Download.id == download_id, Download.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="link_invalid")
    # A quiet reference in the file's metadata ties a leaked copy to this download (and so
    # to its buyer, via our database). Disclosed in the Privacy Policy.
    data, filename = await run_in_threadpool(_render, row.format, Resume.model_validate(row.final_resume),
                                             download_ref(row.id))
    row.served_at = func.now()
    await db.commit()
    return Response(content=data, media_type=_MEDIA[row.format], headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})
