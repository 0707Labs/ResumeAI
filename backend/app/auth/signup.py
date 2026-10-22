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
from app.admin import settings as runtime
from app.billing import ledger, referrals
from app.billing.config import get_billing_config
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
    pending_id, email, invite_id = pending.id, pending.verified_email, pending.invite_id
    # billing.toml plus what staff changed at runtime (invite-only, quota, rewards, starter credits).
    current = await runtime.read_all(db, get_billing_config())
    config, invite_only = runtime.apply(get_billing_config(), current.values), current.values.invite_only
    if invite_id is None and not by_referral and invite_only:
        raise SignupError("invite_required")
    if by_referral and invite_only:
        referrer = await referrals.referrer_for(db, referral_code)
        # take_invite_slot locks the referrer's row: concurrent sign-ups can't exceed the quota.
        if referrer is None or not config.referrals.enabled or not await referrals.take_invite_slot(
                db, config, referrer.id):
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
    invited_by: uuid.UUID | None = None  # a friend's personal email invite: they're the referrer
    invite_bonus = 0  # an admin code's bonus credits
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
            .returning(Invite.id, Invite.kind, Invite.created_by, Invite.bonus_credits)
        )).one_or_none()
        if consumed is not None and consumed.kind == "personal":
            invited_by = consumed.created_by
        if consumed is not None:
            invite_bonus = consumed.bonus_credits or 0
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
    await referrals.attribute(db, config, user, referral_code, ip_hmac=ip_hmac, used_as_invite=by_referral,
                              referrer_id=invited_by)
    # Starter credits ([signup].bonus_credits or its runtime setting) and an invite code's
    # bonus, through the ledger like every credit; keyed so each is granted once.
    if config.signup.bonus_credits > 0:
        await ledger.grant(db, user.id, config.signup.bonus_credits, reason="signup_bonus",
                           idempotency_key=f"signup-bonus:{user.id}", note="starter credits")
    if invite_bonus > 0:
        await ledger.grant(db, user.id, invite_bonus, reason="signup_bonus", idempotency_key=f"invite-bonus:{user.id}",
                           reference_id=str(invite_id), note="invite code bonus")
    await db.execute(delete(PendingAuth).where(PendingAuth.id == pending_id))
    await db.commit()
    return user
