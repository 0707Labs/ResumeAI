"""/app/downloads: what you downloaded, re-download it, or delete it now.

A re-download serves the same file again (the download row's final resume) through a
fresh short-lived signed link, the same kind POST /api/downloads/{fmt} hands out; it
spends nothing, because that download was already paid for. Files are kept for
billing.toml's download retention (the re-download window, by default), then the
retention purge clears them; "expires on" says when. Deleting clears the file now and
keeps the row, so billing and fair-use counts stay right.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import null, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import _LINK, DownloadLink
from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.auth.signing import sign
from app.billing.config import BillingConfig, get_billing_config
from app.db.models import Analysis, Download, User
from app.db.session import get_db

router = APIRouter(prefix="/api/downloads")


def file_name(final_resume: dict | None, fmt: str) -> str:
    """The name the file downloads as (matches app.api.routes._render)."""
    name = (final_resume or {}).get("name") or "resume"
    stem = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "resume"
    return f"{stem}_tailored.{fmt}"


class DownloadItem(BaseModel):
    id: uuid.UUID
    analysis_id: uuid.UUID
    file_name: str
    format: Literal["docx", "pdf"]
    job_title: str | None
    company: str | None
    created_at: datetime
    paid_with: Literal["pass", "pro", "credit", "window"]
    credits: int
    expires_at: datetime  # when the file is cleared (or was)
    available: bool  # the file can still be downloaded again


class DownloadPage(BaseModel):
    items: list[DownloadItem]
    next_before: str | None


@router.get("")
async def history(before: str | None = Query(default=None, max_length=80), limit: int = Query(default=20, ge=1, le=50),
                  user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
                  config: BillingConfig = Depends(get_billing_config)) -> DownloadPage:
    q = (select(Download, Analysis.job_title, Analysis.company)
         .join(Analysis, Analysis.id == Download.analysis_id).where(Download.user_id == user.id))
    if before:
        try:
            at, _, last = before.partition("_")
            q = q.where(tuple_(Download.created_at, Download.id) < (datetime.fromisoformat(at), uuid.UUID(last)))
        except ValueError:
            raise HTTPException(status_code=422, detail="bad_cursor") from None
    rows = (await db.execute(q.order_by(Download.created_at.desc(), Download.id.desc()).limit(limit + 1))).all()
    keep = timedelta(days=config.download_retention_days)
    items = [DownloadItem(
        id=d.id, analysis_id=d.analysis_id, file_name=file_name(d.final_resume, d.format), format=d.format,
        job_title=title, company=company, created_at=d.created_at, paid_with=d.paid_with, credits=d.credits,
        expires_at=d.purged_at or d.created_at + keep, available=d.final_resume is not None)
        for d, title, company in rows[:limit]]
    nxt = rows[limit - 1][0] if len(rows) > limit else None
    return DownloadPage(items=items, next_before=f"{nxt.created_at.isoformat()}_{nxt.id}" if nxt else None)


async def _own(db: AsyncSession, user: User, download_id: uuid.UUID) -> Download:
    row = await db.scalar(select(Download).where(Download.id == download_id, Download.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    return row


@router.post("/{download_id}/link", dependencies=[Depends(rate_limit("redownload", 20, 60)), Depends(require_csrf)])
async def redownload(download_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
                     config: BillingConfig = Depends(get_billing_config)) -> DownloadLink:
    """A fresh signed link to a file you already downloaded. Spends nothing.
    410 file_expired once the file has been cleared."""
    row = await _own(db, user, download_id)
    if row.final_resume is None:
        raise HTTPException(status_code=410, detail="file_expired")
    expires = datetime.now(UTC) + timedelta(seconds=config.downloads.url_ttl_seconds)
    token = sign(_LINK, f"{row.id}:{int(expires.timestamp())}")
    return DownloadLink(url=f"/api/downloads/file/{token}", expires_at=expires, paid_with=row.paid_with,
                        credits_balance=user.credits_balance)


@router.delete("/{download_id}", status_code=204,
               dependencies=[Depends(rate_limit("download_delete", 20, 60)), Depends(require_csrf)])
async def delete_now(download_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> None:
    """Clear the file now; the record of the download stays (what it was, what paid)."""
    row = await _own(db, user, download_id)
    if row.final_resume is not None:
        await db.execute(update(Download).where(Download.id == row.id)
                         .values(final_resume=null(), purged_at=datetime.now(UTC)))
        await db.commit()
