"""The invite gate's last step: one transaction creates the account.

complete_signup consumes one invite use (none needed when RT_INVITE_ONLY is off), creates the user and their first
login method, records the redemption and consent, and drops the pending
identity, all or nothing. Before it commits no user row exists, so nobody gets
an account without a redeemed invite and the required consent."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.signing import ip_ref, subject_ref
from app.billing import ledger, referrals
from app.billing.config import get_billing_config
from app.config import get_settings
from app.db.models import (
    Account,
    ConsentNotice,
    ConsentRecord,
    Invite,
    InviteRedemption,
    PendingAuth,
    User,
)

REQUIRED_PURPOSES = ("age_18_plus", "service")


class SignupError(Exception):
    """code: pending_expired | email_unverified | invite_required | invite_unavailable
    | stale_notice | account_exists"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def current_notices(db: AsyncSession, language: str = "en") -> dict[str, ConsentNotice]:
    """The live notice per purpose: latest published, not retired."""
    now = datetime.now(UTC)
    rows = (await db.execute(
        select(ConsentNotice)
        .where(
            ConsentNotice.language == language,
            ConsentNotice.published_at <= now,
            or_(ConsentNotice.retired_at.is_(None), ConsentNotice.retired_at > now),
        )
        .order_by(ConsentNotice.published_at.desc())
    )).scalars()
    current: dict[str, ConsentNotice] = {}
    for notice in rows:
        current.setdefault(notice.purpose, notice)
    return current


async def complete_signup(
    db: AsyncSession,
    pending: PendingAuth,
    *,
    notice_ids: dict[str, uuid.UUID],
    research_opt_in: bool,
    ip: str | None,
    referral_code: str | None = None,
) -> User:
    """Create the account for a pending identity whose invite step passed.

    `pending` must have been loaded with lock=True in this transaction, so a
    double submit waits and then finds the row gone. Raises SignupError (after
    rolling back) on any failure. The caller confirmed 18+ and Terms consent.

    referral_code (the rt_ref cookie) is attributed in the same transaction; in
    invite-only mode a referral link can stand in for the invite (pending.referral_invite),
    within the referrer's invites_per_user."""
    if pending.kind != "signup" or not pending.verified_email:
        raise SignupError("email_unverified")
    by_referral = pending.invite_id is None and pending.referral_invite
    if pending.invite_id is None and not by_referral and get_settings().invite_only:
        raise SignupError("invite_required")
    pending_id, email, invite_id = pending.id, pending.verified_email, pending.invite_id
    config = get_billing_config()
    if by_referral and get_settings().invite_only:
        referrer = await referrals.referrer_for(db, referral_code)
        if referrer is not None:
            await ledger.lock_user(db, referrer.id)  # serializes use of this referrer's invites
        if referrer is None or not config.referrals.enabled or await referrals.invites_left(
                db, config, referrer.id) == 0:
            await db.rollback()
            await db.execute(update(PendingAuth).where(PendingAuth.id == pending_id).values(referral_invite=False))
            await db.commit()
            raise SignupError("invite_unavailable")

    notices = await current_notices(db)
    purposes = REQUIRED_PURPOSES + (("research",) if research_opt_in else ())
    for purpose in purposes:
        if purpose not in notices or notice_ids.get(purpose) != notices[purpose].id:
            raise SignupError("stale_notice")

    # Consume one use. The row lock serializes concurrent redeemers, and Postgres
    # re-checks the WHERE on the updated row, so the loser sees uses = max_uses.
    # Open signup (RT_INVITE_ONLY off) may arrive with no invite at all.
    now = datetime.now(UTC)
    if invite_id is not None:
        consumed = (await db.execute(
            update(Invite)
            .where(
                Invite.id == invite_id,
                Invite.revoked_at.is_(None),
                or_(Invite.expires_at.is_(None), Invite.expires_at > now),
                Invite.uses < Invite.max_uses,
                or_(Invite.email.is_(None), Invite.email == email),
            )
            .values(uses=Invite.uses + 1)
            .returning(Invite.id)
        )).scalar_one_or_none()
        if consumed is None:
            await db.rollback()
            # Send them back to the invite step.
            await db.execute(update(PendingAuth).where(PendingAuth.id == pending_id).values(invite_id=None))
            await db.commit()
            raise SignupError("invite_unavailable")

    user = User(
        email=email,
        email_verified_at=now,
        activated_at=now,
        age_confirmed_at=now,
        terms_version=notices["service"].version,
        terms_accepted_at=now,
    )
    try:
        db.add(user)
        await db.flush()
        db.add(Account(
            user_id=user.id, provider=pending.provider,
            provider_account_id=pending.provider_account_id, email_at_link=email,
        ))
        if invite_id is not None:
            db.add(InviteRedemption(invite_id=invite_id, user_id=user.id))
        await db.flush()
    except IntegrityError:
        # The email or this provider identity got an account meanwhile (another tab, a race).
        await db.rollback()
        raise SignupError("account_exists") from None

    ref, ip_hmac = subject_ref(email), ip_ref(ip)
    db.add_all([
        ConsentRecord(
            user_id=user.id, subject_ref=ref, notice_id=notices[p].id, purpose=p,
            action="granted", method="signup", ip_hmac=ip_hmac,
        )
        for p in purposes
    ])
    await referrals.attribute(db, config, user, referral_code, ip_hmac=ip_hmac, used_as_invite=by_referral)
    await db.execute(delete(PendingAuth).where(PendingAuth.id == pending_id))
    await db.commit()
    return user
