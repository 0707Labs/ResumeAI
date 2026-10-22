"""Export my data: everything we hold about the signed-in user, as one JSON document.

Runs in the user's own request, so row-level security limits every read to their rows
as well as the explicit filters here. Left out on purpose: session and token hashes,
keyed IP hashes (they identify nothing without our secret, and aren't "about" the user
in a useful way), and other people's data (a referral shows its status, not who the
friend is).
"""

import base64
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Account,
    Analysis,
    ConsentNotice,
    ConsentRecord,
    CreditTransaction,
    Download,
    JobPreferences,
    Pass,
    Payment,
    Referral,
    ResumeVersion,
    SavedResume,
    Subscription,
    User,
    UserAvatar,
)

FORMAT_VERSION = 1


def _plain(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


def _row(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: _plain(getattr(obj, f)) for f in fields}


async def export_user(db: AsyncSession, user: User) -> dict[str, Any]:
    uid = user.id
    doc: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "account": _row(user, ("id", "email", "name", "phone", "role", "status", "created_at", "last_login_at",
                               "terms_version", "terms_accepted_at", "credits_balance", "referral_code",
                               "onboarded_at")),
    }
    doc["login_methods"] = [_row(a, ("provider", "provider_account_id", "email_at_link", "created_at"))
                            for a in await db.scalars(select(Account).where(Account.user_id == uid))]
    avatar = await db.get(UserAvatar, uid)
    doc["picture"] = None if avatar is None else {
        "content_type": avatar.content_type, "source": avatar.source,
        "data_base64": base64.b64encode(avatar.data).decode()}
    prefs = await db.get(JobPreferences, uid)
    doc["job_preferences"] = None if prefs is None else _row(prefs, (
        "target_roles", "seniority", "industries", "locations", "work_modes", "employment_types",
        "notice_period_days", "updated_at"))

    resumes = []
    for r in await db.scalars(select(SavedResume).where(SavedResume.user_id == uid).order_by(SavedResume.created_at)):
        versions = await db.scalars(select(ResumeVersion).where(ResumeVersion.resume_id == r.id)
                                    .order_by(ResumeVersion.version))
        resumes.append({**_row(r, ("id", "title", "is_default", "created_at", "updated_at")),
                        "versions": [{**_row(v, ("version", "source", "file_name", "created_at")), "content": v.content}
                                     for v in versions]})
    doc["saved_resumes"] = resumes

    doc["tailorings"] = [
        {**_row(a, ("id", "job_title", "company", "created_at", "ats_before", "ats_after", "tailored_at",
                    "purged_at", "deleted_at", "mentor_tip")),
         "resume": a.resume, "job_description": a.jd, "tailored": a.tailored}
        for a in await db.scalars(select(Analysis).where(Analysis.user_id == uid).order_by(Analysis.created_at))]
    doc["downloads"] = [
        {**_row(d, ("id", "analysis_id", "format", "paid_with", "credits", "created_at", "served_at", "purged_at")),
         "resume": d.final_resume}
        for d in await db.scalars(select(Download).where(Download.user_id == uid).order_by(Download.created_at))]
    doc["credit_ledger"] = [
        _row(t, ("id", "delta", "reason", "balance_after", "note", "created_at"))
        for t in await db.scalars(select(CreditTransaction).where(CreditTransaction.user_id == uid)
                                  .order_by(CreditTransaction.id))]
    doc["payments"] = [
        _row(p, ("id", "product_key", "kind", "status", "currency", "amount_minor", "tax_minor",
                 "refunded_amount_minor", "provider_payment_id", "created_at", "paid_at"))
        for p in await db.scalars(select(Payment).where(Payment.user_id == uid).order_by(Payment.created_at))]
    doc["passes"] = [_row(p, ("product_key", "starts_at", "expires_at", "analyses_cap", "revoked_at"))
                     for p in await db.scalars(select(Pass).where(Pass.user_id == uid))]
    doc["subscriptions"] = [_row(s, ("product_key", "status", "current_period_end", "cancel_at_period_end",
                                     "created_at")) for s in await db.scalars(select(Subscription)
                                                                               .where(Subscription.user_id == uid))]
    doc["referrals_made"] = [_row(r, ("status", "reward_credits", "created_at", "rewarded_at"))
                             for r in await db.scalars(select(Referral).where(Referral.referrer_id == uid))]
    doc["referred_by_someone"] = (await db.scalar(select(Referral.id).where(Referral.referee_id == uid))) is not None
    doc["consents"] = [
        {"purpose": c.purpose, "action": c.action, "method": c.method, "notice_version": n.version,
         "notice_url": n.body_url, "at": c.created_at.isoformat()}
        for c, n in (await db.execute(select(ConsentRecord, ConsentNotice)
                                      .join(ConsentNotice, ConsentNotice.id == ConsentRecord.notice_id)
                                      .where(ConsentRecord.user_id == uid).order_by(ConsentRecord.id))).all()]
    return doc
