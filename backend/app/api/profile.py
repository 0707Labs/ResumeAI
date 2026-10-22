"""The signed-in user area: profile basics, job preferences, saved resumes, plan, dashboard.

Every route runs under current_user, so the request's DB session is limited to the
caller's rows by row-level security (app.db.rls) on top of the user_id filters here.
Writes take CSRF and a rate limit like the other account endpoints.
"""

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, func, null, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.billing import referrals
from app.admin.settings import live_billing_config
from app.billing.config import BillingConfig
from app.billing.plan import Kind, plan_status
from app.db.models import (
    EMPLOYMENT_TYPES,
    SENIORITY_LEVELS,
    WORK_MODES,
    Analysis,
    Download,
    JobPreferences,
    Referral,
    ResumeVersion,
    SavedResume,
    User,
    UserAvatar,
)
from app.db.session import get_db
from app.models.jd import JobDescription
from app.models.resume import Resume
from app.models.tailor import TailoredResume
from app.profile import avatars

router = APIRouter(prefix="/api")
WRITE = [Depends(rate_limit("profile_write", 30, 60)), Depends(require_csrf)]
MAX_RESUMES = 20
MAX_VERSIONS = 100

Seniority = Literal[SENIORITY_LEVELS]  # type: ignore[valid-type]
WorkMode = Literal[WORK_MODES]  # type: ignore[valid-type]
EmploymentType = Literal[EMPLOYMENT_TYPES]  # type: ignore[valid-type]


# --- profile -----------------------------------------------------------------------------------


PHONE_RE = re.compile(r"^\+[1-9][0-9]{6,14}$")


class ProfileIn(BaseModel):
    """Only the fields sent are changed; phone null clears it."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            raise ValueError("name can't be cleared")
        v = " ".join(v.split())
        if not v:
            raise ValueError("name is empty")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = re.sub(r"[\s().-]", "", v)
        if not v:
            return None
        if not PHONE_RE.match(v):
            raise ValueError("use international format, like +91 98765 43210")
        return v


class ProfileOut(BaseModel):
    name: str | None
    email: str
    phone: str | None
    avatar_url: str | None
    avatar_source: Literal["provider", "upload"] | None


@router.get("/profile")
async def get_profile(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> ProfileOut:
    row = (await db.execute(select(UserAvatar.sha256, UserAvatar.source)
                            .where(UserAvatar.user_id == user.id))).one_or_none()
    return ProfileOut(name=user.name, email=user.email, phone=user.phone,
                      avatar_url=avatars.url(row.sha256 if row else None), avatar_source=row.source if row else None)


@router.patch("/profile", dependencies=WRITE)
async def update_profile(body: ProfileIn, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)) -> ProfileOut:
    sent = body.model_fields_set
    if "name" in sent:
        user.name = body.name
    if "phone" in sent:
        user.phone = body.phone
    await db.commit()
    return await get_profile(user, db)


@router.get("/profile/avatar")
async def get_avatar(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> Response:
    row = await db.get(UserAvatar, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="no_avatar")
    # Private: only this user's session can read it; shared caches must not keep it.
    return Response(row.data, media_type=row.content_type, headers={
        "Cache-Control": "private, max-age=86400", "ETag": f'"{row.sha256[:32]}"',
        "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"})


@router.put("/profile/avatar", dependencies=[Depends(rate_limit("avatar_upload", 10, 3600)), Depends(require_csrf)])
async def upload_avatar(file: UploadFile, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)) -> ProfileOut:
    """PNG, JPEG, WebP or GIF up to 2 MB; stored re-encoded as a 256 px WebP."""
    raw = await file.read(avatars.MAX_INPUT_BYTES + 1)
    try:
        data = avatars.normalize(raw)
    except avatars.BadImage as exc:
        raise HTTPException(status_code=413 if str(exc) == "too_large" else 415, detail=f"avatar_{exc}") from None
    await avatars.save(db, user.id, data, "upload")
    user.avatar_removed_at = None
    await db.commit()
    return await get_profile(user, db)


@router.delete("/profile/avatar", dependencies=WRITE)
async def delete_avatar(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> ProfileOut:
    await avatars.remove(db, user)
    await db.commit()
    return await get_profile(user, db)


@router.post("/profile/onboarded", status_code=204, dependencies=WRITE)
async def finish_onboarding(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> None:
    """The first-login wizard is done or skipped. Idempotent."""
    if user.onboarded_at is None:
        user.onboarded_at = datetime.now(UTC)
        await db.commit()


# --- job preferences ---------------------------------------------------------------------------

def _clean_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        v = " ".join(v.split())
        if v and v.lower() not in {o.lower() for o in out}:
            out.append(v)
    return out


class Preferences(BaseModel):
    target_roles: list[str] = Field(default_factory=list, max_length=10)
    seniority: Seniority | None = None
    industries: list[str] = Field(default_factory=list, max_length=10)
    locations: list[str] = Field(default_factory=list, max_length=10)
    work_modes: list[WorkMode] = Field(default_factory=list, max_length=3)
    employment_types: list[EmploymentType] = Field(default_factory=list, max_length=5)
    notice_period_days: int | None = Field(default=None, ge=0, le=365)

    @field_validator("target_roles", "industries", "locations")
    @classmethod
    def _items(cls, values: list[str]) -> list[str]:
        values = _clean_list(values)
        if any(len(v) > 80 for v in values):
            raise ValueError("each entry must be 80 characters or fewer")
        return values

    @field_validator("work_modes", "employment_types")
    @classmethod
    def _unique(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class PreferencesOut(Preferences):
    updated_at: datetime | None


@router.get("/profile/preferences")
async def get_preferences(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> PreferencesOut:
    row = await db.get(JobPreferences, user.id)
    if row is None:
        return PreferencesOut(updated_at=None)
    return PreferencesOut(target_roles=row.target_roles, seniority=row.seniority, industries=row.industries,
                          locations=row.locations, work_modes=row.work_modes, employment_types=row.employment_types,
                          notice_period_days=row.notice_period_days, updated_at=row.updated_at)


@router.put("/profile/preferences", dependencies=WRITE)
async def put_preferences(body: Preferences, user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)) -> PreferencesOut:
    values = body.model_dump()
    await db.execute(insert(JobPreferences).values(user_id=user.id, **values).on_conflict_do_update(
        index_elements=[JobPreferences.user_id], set_={**values, "updated_at": func.now()}))
    await db.commit()
    return await get_preferences(user, db)


# --- saved resumes -----------------------------------------------------------------------------


class ResumeIn(BaseModel):
    resume: Resume
    title: str | None = Field(default=None, max_length=120)
    source: Literal["upload", "paste"]
    file_name: str | None = Field(default=None, max_length=200)


class ResumeSummary(BaseModel):
    id: uuid.UUID
    title: str
    is_default: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ResumeDetail(ResumeSummary):
    shown_version: int  # the version in `resume` (the latest unless ?version= asked otherwise)
    source: Literal["upload", "paste", "edit"]
    resume: Resume


def _title(body: ResumeIn) -> str:
    if body.title and body.title.strip():
        return body.title.strip()[:120]
    if body.file_name:
        stem = body.file_name.rsplit("/", 1)[-1].rsplit(".", 1)[0].strip()
        if stem:
            return stem[:120]
    return f"{body.resume.name}'s resume"[:120] if body.resume.name else "My resume"


@router.post("/resumes", status_code=201, dependencies=WRITE)
async def save_resume(body: ResumeIn, user: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)) -> ResumeSummary:
    """Keep a base resume. The first one becomes the default. Saved resumes aren't purged;
    the user deletes them."""
    count = int(await db.scalar(select(func.count()).select_from(SavedResume)
                                .where(SavedResume.user_id == user.id)) or 0)
    if count >= MAX_RESUMES:
        raise HTTPException(status_code=409, detail="resume_limit")
    uid, title, content = user.id, _title(body), body.resume.model_dump(mode="json")
    for make_default in (count == 0, False):  # a concurrent first save may take the default
        row = SavedResume(id=uuid.uuid4(), user_id=uid, title=title, is_default=make_default)
        try:
            db.add(row)
            await db.flush()  # the resume first: a version's owner is checked against it
            db.add(ResumeVersion(resume_id=row.id, user_id=uid, version=1, source=body.source,
                                 file_name=body.file_name, content=content))
            await db.commit()
            break
        except IntegrityError:
            await db.rollback()
            if not make_default:
                raise
    await db.refresh(row)
    return ResumeSummary(id=row.id, title=row.title, is_default=row.is_default, version=1,
                         created_at=row.created_at, updated_at=row.updated_at)


def _latest_versions():
    return (select(ResumeVersion.resume_id, func.max(ResumeVersion.version).label("version"))
            .group_by(ResumeVersion.resume_id).subquery())


@router.get("/resumes")
async def list_resumes(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[ResumeSummary]:
    latest = _latest_versions()
    rows = (await db.execute(
        select(SavedResume, latest.c.version).join(latest, latest.c.resume_id == SavedResume.id)
        .where(SavedResume.user_id == user.id)
        .order_by(SavedResume.is_default.desc(), SavedResume.updated_at.desc()))).all()
    return [ResumeSummary(id=r.id, title=r.title, is_default=r.is_default, version=v, created_at=r.created_at,
                          updated_at=r.updated_at) for r, v in rows]


async def _own_resume(db: AsyncSession, user: User, resume_id: uuid.UUID, *, lock: bool = False) -> SavedResume:
    q = select(SavedResume).where(SavedResume.id == resume_id, SavedResume.user_id == user.id)
    row = await db.scalar(q.with_for_update() if lock else q)
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    return row


async def _latest(db: AsyncSession, resume_id: uuid.UUID) -> ResumeVersion:
    return await db.scalar(select(ResumeVersion).where(ResumeVersion.resume_id == resume_id)
                           .order_by(ResumeVersion.version.desc()).limit(1))


def _detail(row: SavedResume, version: ResumeVersion, latest: int) -> "ResumeDetail":
    return ResumeDetail(id=row.id, title=row.title, is_default=row.is_default, version=latest,
                        created_at=row.created_at, updated_at=row.updated_at, shown_version=version.version,
                        source=version.source, resume=Resume.model_validate(version.content))


@router.get("/resumes/{resume_id}")
async def get_resume(resume_id: uuid.UUID, version: int | None = Query(default=None, ge=1),
                     user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> "ResumeDetail":
    """The latest version, or ?version=N to look at an older one."""
    row = await _own_resume(db, user, resume_id)
    latest = await _latest(db, row.id)
    shown = latest if version is None else await db.scalar(select(ResumeVersion).where(
        ResumeVersion.resume_id == row.id, ResumeVersion.version == version))
    if shown is None:
        raise HTTPException(status_code=404, detail="no_such_version")
    return _detail(row, shown, latest.version)


class VersionSummary(BaseModel):
    version: int
    source: Literal["upload", "paste", "edit"]
    file_name: str | None
    created_at: datetime


@router.get("/resumes/{resume_id}/versions")
async def list_versions(resume_id: uuid.UUID, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)) -> list[VersionSummary]:
    row = await _own_resume(db, user, resume_id)
    versions = await db.scalars(select(ResumeVersion).where(ResumeVersion.resume_id == row.id)
                                .order_by(ResumeVersion.version.desc()))
    return [VersionSummary(version=v.version, source=v.source, file_name=v.file_name, created_at=v.created_at)
            for v in versions]


class VersionIn(BaseModel):
    resume: Resume
    source: Literal["edit", "upload", "paste"]
    file_name: str | None = Field(default=None, max_length=200)


def check_bullet_ids(resume: Resume) -> None:
    """Edits keep bullet ids stable: each bullet's id is '<its entry id>.b<n>', so a tailored
    bullet's source_bullet_id keeps pointing at the same line."""
    for entry in resume.entries():
        for bullet in entry.bullets:
            if not bullet.id.startswith(f"{entry.id}.b"):
                raise HTTPException(status_code=422, detail="bullet_id_mismatch")


@router.post("/resumes/{resume_id}/versions", status_code=201, dependencies=WRITE)
async def add_version(resume_id: uuid.UUID, body: VersionIn, user: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)) -> "ResumeDetail":
    """Save an edit or a replacement upload as the next version; older versions stay."""
    if body.source == "edit":
        check_bullet_ids(body.resume)
    row = await _own_resume(db, user, resume_id, lock=True)  # serializes version numbers
    latest = await _latest(db, row.id)
    if latest.version >= MAX_VERSIONS:
        raise HTTPException(status_code=409, detail="version_limit")
    version = ResumeVersion(resume_id=row.id, user_id=user.id, version=latest.version + 1, source=body.source,
                            file_name=body.file_name, content=body.resume.model_dump(mode="json"))
    db.add(version)
    row.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return _detail(row, version, version.version)


class ResumePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    is_default: Literal[True] | None = None  # make this the default; there's always one when any exist


@router.patch("/resumes/{resume_id}", dependencies=WRITE)
async def update_resume(resume_id: uuid.UUID, body: ResumePatch, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)) -> ResumeSummary:
    row = await _own_resume(db, user, resume_id, lock=True)
    if body.title is not None:
        row.title = body.title.strip() or row.title
    if body.is_default and not row.is_default:
        await db.execute(update(SavedResume).where(SavedResume.user_id == user.id, SavedResume.is_default)
                         .values(is_default=False))
        await db.flush()
        row.is_default = True
    row.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return ResumeSummary(id=row.id, title=row.title, is_default=row.is_default,
                         version=(await _latest(db, row.id)).version, created_at=row.created_at,
                         updated_at=row.updated_at)


@router.post("/resumes/{resume_id}/duplicate", status_code=201, dependencies=WRITE)
async def duplicate_resume(resume_id: uuid.UUID, user: User = Depends(current_user),
                           db: AsyncSession = Depends(get_db)) -> ResumeSummary:
    row = await _own_resume(db, user, resume_id)
    latest = await _latest(db, row.id)
    body = ResumeIn(resume=Resume.model_validate(latest.content), title=f"{row.title} (copy)"[:120], source="paste")
    return await save_resume(body, user, db)


@router.delete("/resumes/{resume_id}", status_code=204, dependencies=WRITE)
async def delete_resume(resume_id: uuid.UUID, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)) -> None:
    """Deletes every version. Tailorings made from it keep their own copy until the purge.
    If it was the default, the most recently updated other resume becomes the default."""
    row = await _own_resume(db, user, resume_id, lock=True)
    was_default, uid = row.is_default, user.id
    await db.delete(row)
    await db.flush()
    if was_default:
        nxt = await db.scalar(select(SavedResume).where(SavedResume.user_id == uid)
                              .order_by(SavedResume.updated_at.desc()).limit(1))
        if nxt is not None:
            nxt.is_default = True
    await db.commit()


# --- tailorings (analyses) -----------------------------------------------------------------------


class TailoringSummary(BaseModel):
    id: uuid.UUID
    job_title: str | None
    company: str | None
    created_at: datetime
    ats_before: float | None
    ats_after: float | None
    status: Literal["started", "tailored", "downloaded"]
    resume_id: uuid.UUID | None
    content_available: bool  # False once the retention purge cleared its text


class TailoringPage(BaseModel):
    items: list[TailoringSummary]
    next_before: str | None  # pass back as ?before= for the next (older) page


def _status_expr():
    return exists().where(Download.analysis_id == Analysis.id)


@router.get("/tailorings")
async def list_tailorings(before: str | None = Query(default=None, max_length=80),
                          limit: int = Query(default=20, ge=1, le=50),
                          user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> TailoringPage:
    """Newest first, paged by a (created_at, id) cursor. Metadata only."""
    q = (select(Analysis.id, Analysis.job_title, Analysis.company, Analysis.created_at, Analysis.ats_before,
                Analysis.ats_after, Analysis.tailored_at, Analysis.resume_id, Analysis.purged_at,
                _status_expr().label("downloaded"))
         .where(Analysis.user_id == user.id, Analysis.deleted_at.is_(None)))
    if before:
        try:
            at, _, last = before.partition("_")
            q = q.where(tuple_(Analysis.created_at, Analysis.id) < (datetime.fromisoformat(at), uuid.UUID(last)))
        except ValueError:
            raise HTTPException(status_code=422, detail="bad_cursor") from None
    rows = (await db.execute(q.order_by(Analysis.created_at.desc(), Analysis.id.desc()).limit(limit + 1))).all()
    items = [TailoringSummary(
        id=r.id, job_title=r.job_title, company=r.company, created_at=r.created_at,
        ats_before=_num(r.ats_before), ats_after=_num(r.ats_after),
        status="downloaded" if r.downloaded else "tailored" if r.tailored_at else "started",
        resume_id=r.resume_id, content_available=r.purged_at is None) for r in rows[:limit]]
    nxt = rows[limit - 1] if len(rows) > limit else None
    return TailoringPage(items=items, next_before=f"{nxt.created_at.isoformat()}_{nxt.id}" if nxt else None)


class TailoringDetail(TailoringSummary):
    resume: Resume | None
    jd: JobDescription | None
    tailored: TailoredResume | None


@router.get("/tailorings/{analysis_id}")
async def get_tailoring(analysis_id: uuid.UUID, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)) -> TailoringDetail:
    """One tailoring, with its resume, job description and result while they're kept."""
    row = await db.scalar(select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user.id,
                                                 Analysis.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    downloaded = await db.scalar(select(exists().where(Download.analysis_id == row.id)))
    return TailoringDetail(
        id=row.id, job_title=row.job_title, company=row.company, created_at=row.created_at,
        ats_before=_num(row.ats_before), ats_after=_num(row.ats_after),
        status="downloaded" if downloaded else "tailored" if row.tailored_at else "started",
        resume_id=row.resume_id, content_available=row.purged_at is None,
        resume=Resume.model_validate(row.resume) if row.resume else None,
        jd=JobDescription.model_validate(row.jd) if row.jd else None,
        tailored=TailoredResume.model_validate(row.tailored) if row.tailored else None)


@router.delete("/tailorings/{analysis_id}", status_code=204, dependencies=WRITE)
async def delete_tailoring(analysis_id: uuid.UUID, user: User = Depends(current_user),
                           db: AsyncSession = Depends(get_db)) -> None:
    """Delete a tailoring: its resume, job description, result, mentor tip and the files
    downloaded from it are cleared now. The row stays (ids, dates, what paid), so credits,
    caps and the free allowance count the same."""
    now = datetime.now(UTC)
    row = await db.scalar(select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user.id,
                                                 Analysis.deleted_at.is_(None)).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    # null(): SQL NULL. A plain None on a JSONB attribute would store JSON 'null'.
    await db.execute(update(Analysis).where(Analysis.id == row.id).values(
        resume=null(), jd=null(), tailored=null(), mentor_tip=None, purged_at=func.coalesce(Analysis.purged_at, now),
        deleted_at=now, usable_until=func.least(Analysis.usable_until, now)))
    await db.execute(update(Download).where(Download.analysis_id == row.id, Download.purged_at.is_(None))
                     .values(final_resume=null(), purged_at=now))
    await db.commit()


# --- plan and dashboard ------------------------------------------------------------------------


class PlanOut(BaseModel):
    kind: Kind
    credits: int
    pass_expires_at: datetime | None
    pass_days_left: int | None
    pass_downloads_left: int | None
    pro_period_end: datetime | None
    free_allowance: int
    free_left: int
    resets_at: datetime


@router.get("/plan")
async def plan(user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
               config: BillingConfig = Depends(live_billing_config)) -> PlanOut:
    return PlanOut(**(await plan_status(db, config, user, datetime.now(UTC))).__dict__)


class RecentTailoring(BaseModel):
    id: uuid.UUID
    job_title: str | None
    company: str | None
    created_at: datetime
    ats_before: float | None
    ats_after: float | None
    status: Literal["started", "tailored", "downloaded"]


class MentorTip(BaseModel):
    text: str
    job_title: str | None
    company: str | None
    created_at: datetime


class ReferralProgress(BaseModel):
    enabled: bool
    invites_per_user: int
    invites_left: int
    joined: int
    rewarded: int
    credits_earned: int


class DashboardOut(BaseModel):
    name: str | None
    plan: PlanOut
    recent: list[RecentTailoring]
    last_tip: MentorTip | None
    referrals: ReferralProgress
    has_resume: bool
    has_preferences: bool


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


@router.get("/dashboard")
async def dashboard(user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
                    config: BillingConfig = Depends(live_billing_config)) -> DashboardOut:
    """Everything /app/dashboard shows, in one call. Metadata only: no resume or JD text."""
    now = datetime.now(UTC)
    downloaded = exists().where(Download.analysis_id == Analysis.id)
    rows = (await db.execute(
        select(Analysis.id, Analysis.job_title, Analysis.company, Analysis.created_at, Analysis.ats_before,
               Analysis.ats_after, Analysis.tailored_at, downloaded.label("downloaded"))
        .where(Analysis.user_id == user.id, Analysis.deleted_at.is_(None))
        .order_by(Analysis.created_at.desc()).limit(5))).all()
    recent = [RecentTailoring(id=r.id, job_title=r.job_title, company=r.company, created_at=r.created_at,
                              ats_before=_num(r.ats_before), ats_after=_num(r.ats_after),
                              status="downloaded" if r.downloaded else "tailored" if r.tailored_at else "started")
              for r in rows]
    tip_row = (await db.execute(
        select(Analysis.mentor_tip, Analysis.job_title, Analysis.company, Analysis.created_at)
        .where(Analysis.user_id == user.id, Analysis.deleted_at.is_(None), Analysis.mentor_tip.is_not(None))
        .order_by(Analysis.created_at.desc()).limit(1))).one_or_none()

    mine = list(await db.scalars(select(Referral).where(Referral.referrer_id == user.id)))
    progress = ReferralProgress(
        enabled=config.referrals.enabled, invites_per_user=config.referrals.invites_per_user,
        invites_left=await referrals.invites_left(db, config, user.id), joined=len(mine),
        rewarded=sum(1 for r in mine if r.status == "rewarded"),
        credits_earned=sum(r.reward_credits for r in mine if r.status == "rewarded"))

    return DashboardOut(
        name=user.name, plan=PlanOut(**(await plan_status(db, config, user, now)).__dict__), recent=recent,
        last_tip=MentorTip(text=tip_row.mentor_tip, job_title=tip_row.job_title, company=tip_row.company,
                           created_at=tip_row.created_at) if tip_row else None,
        referrals=progress,
        has_resume=bool(await db.scalar(select(exists().where(SavedResume.user_id == user.id)))),
        has_preferences=await db.get(JobPreferences, user.id) is not None,
    )
