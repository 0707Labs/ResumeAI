import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from app.analysis import AnswerError, analyze, apply_answers, refine_with_llm
from app.config import get_settings
from app.export.render import to_docx, to_pdf
from app.llm.client import get_llm
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
from app.parsing import (
    MAX_BYTES,
    ExtractionError,
    UnsupportedFileType,
    parse_jd,
    parse_resume_file,
)

router = APIRouter()


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
def gap_analyze(body: GapRequest) -> GapAnalysis:
    analysis = analyze(body.resume, body.jd)
    llm = get_llm() if body.use_llm else None
    if llm is None:
        note = "Rules only." if not body.use_llm else "Rules only (no ANTHROPIC_API_KEY set)."
        return analysis.model_copy(update={"notes": [note]})
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
def tailor_resume(body: TailorRequest) -> TailoredResume:
    llm = get_llm() if body.use_llm else None
    result = tailor(body.resume, body.jd, body.analysis, llm)
    if body.use_llm and llm is None:
        result.notes.insert(0, "No ANTHROPIC_API_KEY set.")
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


class ScoreResponse(BaseModel):
    before: ATSReport
    after: ATSReport | None = None
    delta: float | None = None


@router.post("/api/ats/score")
def ats_score(body: ScoreRequest) -> ScoreResponse:
    llm = get_llm() if body.use_llm else None
    before = score(body.resume, body.jd, llm=llm)
    if body.tailored is None:
        return ScoreResponse(before=before)
    checked = reverify(body.tailored, body.resume, body.analysis, body.jd.raw_text)
    after = score(apply_tailoring(body.resume, checked), body.jd, llm=llm)
    return ScoreResponse(before=before, after=after, delta=round(after.total - before.total, 1))


class MentorRequest(BaseModel):
    resume: Resume
    jd: JobDescription
    analysis: GapAnalysis | None = None  # computed (rules only) if omitted
    ats: ATSReport | None = None  # computed (rules only) if omitted
    use_llm: bool = True


@router.post("/api/mentor")
def mentor(body: MentorRequest) -> MentorAdvice:
    analysis = body.analysis or analyze(body.resume, body.jd)
    ats = body.ats or score(body.resume, body.jd)
    advice = build_advice(body.resume, body.jd, analysis, ats)
    llm = get_llm() if body.use_llm else None
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


@router.post("/api/export/{fmt}")
def export(fmt: Literal["docx", "pdf"], body: ExportRequest) -> Response:
    """Only bullets that pass verification now AND were approved by the user use
    tailored text; everything else exports in its original wording."""
    checked = reverify(body.tailored, body.resume, body.analysis, body.jd_text)
    final = apply_tailoring(body.resume, checked, approved_only=True)
    data = to_docx(final) if fmt == "docx" else to_pdf(final)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", final.name or "resume").strip("_") or "resume"
    return Response(content=data, media_type=_MEDIA[fmt], headers={
        "Content-Disposition": f'attachment; filename="{stem}_tailored.{fmt}"'})
