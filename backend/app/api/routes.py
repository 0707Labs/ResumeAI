from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.analysis import AnswerError, analyze, apply_answers, refine_with_llm
from app.config import get_settings
from app.llm.client import get_llm
from app.models import WEIGHTS, GapAnalysis, JobDescription, Resume
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
    answers: dict[str, str]


@router.post("/api/gap/answers")
def gap_answers(body: AnswersRequest) -> GapAnalysis:
    try:
        return apply_answers(body.analysis, body.answers)
    except AnswerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
