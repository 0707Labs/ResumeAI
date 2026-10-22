"""The signed-in user area: profile basics, job preferences, saved resumes, plan, dashboard.

Every route runs under current_user, so the request's DB session is limited to the
caller's rows by row-level security (app.db.rls) on top of the user_id filters here.
Writes take CSRF and a rate limit like the other account endpoints.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.billing import referrals
from app.billing.config import BillingConfig, get_billing_config
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
)
from app.db.session import get_db
from app.models.resume import Resume

router = APIRouter(prefix="/api")
WRITE = [Depends(rate_limit("profile_write", 30, 60)), Depends(require_csrf)]
MAX_RESUMES = 20

Seniority = Literal[SENIORITY_LEVELS]  # type: ignore[valid-type]
WorkMode = Literal[WORK_MODES]  # type: ignore[valid-type]
EmploymentType = Literal[EMPLOYMENT_TYPES]  # type: ignore[valid-type]


# --- profile -----------------------------------------------------------------------------------


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name is empty")
        return v


@router.patch("/profile", status_code=204, dependencies=WRITE)
async def update_profile(body: ProfileIn, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)) -> None:
    user.name = body.name
    await db.commit()


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


@router.get("/resumes/{resume_id}")
async def get_resume(resume_id: uuid.UUID, user: User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)) -> ResumeDetail:
    row = await db.scalar(select(SavedResume).where(SavedResume.id == resume_id, SavedResume.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    version = await db.scalar(select(ResumeVersion).where(ResumeVersion.resume_id == row.id)
                              .order_by(ResumeVersion.version.desc()).limit(1))
    return ResumeDetail(id=row.id, title=row.title, is_default=row.is_default, version=version.version,
                        created_at=row.created_at, updated_at=row.updated_at,
                        resume=Resume.model_validate(version.content))


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
               config: BillingConfig = Depends(get_billing_config)) -> PlanOut:
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
                    config: BillingConfig = Depends(get_billing_config)) -> DashboardOut:
    """Everything /app/dashboard shows, in one call. Metadata only: no resume or JD text."""
    now = datetime.now(UTC)
    downloaded = exists().where(Download.analysis_id == Analysis.id)
    rows = (await db.execute(
        select(Analysis.id, Analysis.job_title, Analysis.company, Analysis.created_at, Analysis.ats_before,
               Analysis.ats_after, Analysis.tailored_at, downloaded.label("downloaded"))
        .where(Analysis.user_id == user.id).order_by(Analysis.created_at.desc()).limit(5))).all()
    recent = [RecentTailoring(id=r.id, job_title=r.job_title, company=r.company, created_at=r.created_at,
                              ats_before=_num(r.ats_before), ats_after=_num(r.ats_after),
                              status="downloaded" if r.downloaded else "tailored" if r.tailored_at else "started")
              for r in rows]
    tip_row = (await db.execute(
        select(Analysis.mentor_tip, Analysis.job_title, Analysis.company, Analysis.created_at)
        .where(Analysis.user_id == user.id, Analysis.mentor_tip.is_not(None))
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
