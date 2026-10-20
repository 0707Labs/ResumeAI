from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import get_settings
from app.models import WEIGHTS, JobDescription, Resume
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
