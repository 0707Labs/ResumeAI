"""Referrals: a friend who signs up with your link earns you credits.

Flow: the landing page stores ?ref=CODE in the rt_ref cookie; the account-creating
transaction (app.auth.signup.complete_signup) calls attribute(), which records one
referral per new account and rejects or flags abuse up front. The reward fires on the
configured trigger ([referrals].trigger): at sign-up (the email is verified by then) or
on the friend's first finished tailoring (on_first_tailoring(), called by /api/tailor).
maybe_reward() pays through the ledger (reason 'referral', key referral:{id}), at most
[referrals].monthly_cap times per referrer per calendar month. Admins approve or reject
flagged ones and can reverse a paid one (credits taken back, never below zero).

Abuse controls: no self-referral, no same-person aliases (gmail dots and +tags, any
+tag), disposable email domains rejected, and referred sign-ups clustering on one
network (keyed IP hash) wait for review instead of paying. We don't fingerprint devices.

Every function runs inside the caller's transaction and never commits. Rewards lock the
referrer's user row first (as the ledger does), so concurrent triggers can't exceed the
cap or pay twice.
"""

import logging
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.invites import ALPHABET
from app.billing import ledger
from app.billing.analyses import month_start
from app.billing.config import BillingConfig
from app.db.models import Analysis, Referral, User
from app.db.rls import service_scope

log = logging.getLogger("app.billing")

COOKIE = "rt_ref"
CODE_RE = re.compile(r"^[A-Z2-9]{8}$")

# A starter list; [referrals].extra_disposable_domains adds to it.
DISPOSABLE_DOMAINS = frozenset({
    "10minutemail.com", "20minutemail.com", "33mail.com", "anonaddy.me", "burnermail.io", "discard.email",
    "dispostable.com", "emailondeck.com", "fakeinbox.com", "getairmail.com", "getnada.com", "guerrillamail.com",
    "guerrillamail.net", "guerrillamailblock.com", "inboxkitten.com", "maildrop.cc", "mailinator.com",
    "mailnesia.com", "mintemail.com", "mohmal.com", "moakt.com", "mytemp.email", "sharklasers.com",
    "spamgourmet.com", "temp-mail.org", "tempmail.com", "tempmail.dev", "tempmailo.com", "tempr.email",
    "throwawaymail.com", "trashmail.com", "yopmail.com", "yopmail.net",
})
GMAIL = {"gmail.com", "googlemail.com"}


def normalize_code(code: str | None) -> str | None:
    clean = re.sub(r"[^A-Z0-9]", "", (code or "").upper())
    return clean if CODE_RE.match(clean) else None


def same_person_key(email: str) -> str:
    """One key for an address and its aliases: no +tag, and for Gmail no dots."""
    local, _, domain = email.lower().strip().partition("@")
    local = local.split("+", 1)[0]
    if domain in GMAIL:
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def is_disposable(email: str, config: BillingConfig) -> bool:
    domain = email.lower().rsplit("@", 1)[-1]
    extra = {d.lower() for d in config.referrals.extra_disposable_domains}
    return any(domain == d or domain.endswith("." + d) for d in DISPOSABLE_DOMAINS | extra)


async def ensure_code(db: AsyncSession, user: User) -> str:
    """The user's referral code, made on first use. Caller commits."""
    if user.referral_code:
        return user.referral_code
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        async with service_scope(db):  # uniqueness is a question about every user's code
            taken = await db.scalar(select(User.id).where(User.referral_code == code))
        if taken is None:
            user.referral_code = code
            await db.flush()
            return code


async def referrer_for(db: AsyncSession, code: str | None) -> User | None:
    code = normalize_code(code)
    if code is None:
        return None
    return await db.scalar(select(User).where(
        User.referral_code == code, User.status == "active", User.deleted_at.is_(None)))


async def invites_left(db: AsyncSession, config: BillingConfig, user_id: uuid.UUID) -> int:
    """Invite slots left: one quota for email invites and referral-link sign-ups."""
    used = await db.scalar(select(User.invites_created).where(User.id == user_id))
    return max(config.referrals.invites_per_user - int(used or 0), 0)


async def take_invite_slot(db: AsyncSession, config: BillingConfig, user_id: uuid.UUID) -> bool:
    """Use one of the referrer's slots for a sign-up through their link (locks their row)."""
    return bool(await db.scalar(text("SELECT take_invite_slot(:u, :n)"),
                                {"u": user_id, "n": config.referrals.invites_per_user}))


async def attribute(db: AsyncSession, config: BillingConfig, referee: User, code: str | None, *,
                    ip_hmac: str | None, used_as_invite: bool = False, now: datetime | None = None,
                    referrer_id: uuid.UUID | None = None) -> Referral | None:
    """Record that `referee` (just created) came through `code`, or through a personal
    email invite from `referrer_id` (which wins over a link cookie). Returns None when
    there's nothing to record (no or unknown referrer, referrals off). Abuse is recorded
    as rejected or flagged, so the admin queue sees it."""
    if not config.referrals.enabled:
        return None
    referrer = (await db.scalar(select(User).where(User.id == referrer_id, User.status == "active",
                                                   User.deleted_at.is_(None)))
                if referrer_id else await referrer_for(db, code))
    if referrer is None:
        return None
    if await db.scalar(select(Referral.id).where(Referral.referee_id == referee.id)) is not None:
        return None  # a referee is attributed once (also a unique index)
    now = now or datetime.now(UTC)
    row = Referral(id=uuid.uuid4(), referrer_id=referrer.id, referee_id=referee.id, ip_hmac=ip_hmac,
                   used_as_invite=used_as_invite, created_at=now)
    if referrer.id == referee.id or same_person_key(referrer.email) == same_person_key(referee.email):
        row.status, row.reason = "rejected", "same_person"
    elif is_disposable(referee.email, config):
        row.status, row.reason = "rejected", "disposable_email"
    elif ip_hmac is not None:
        since = now - timedelta(hours=config.referrals.review_window_hours)
        cluster = await db.scalar(select(func.count()).select_from(Referral).where(
            Referral.ip_hmac == ip_hmac, Referral.created_at >= since))
        if int(cluster) + 1 >= config.referrals.same_ip_review_threshold:
            row.needs_review, row.reason = True, "same_network"
    db.add(row)
    await db.flush()
    log.info("referral recorded id=%s referrer=%s referee=%s status=%s reason=%s",
             row.id, row.referrer_id, row.referee_id, row.status, row.reason)
    if config.referrals.trigger == "on_verified_signup":
        await maybe_reward(db, config, row, now=now)
    return row


async def maybe_reward(db: AsyncSession, config: BillingConfig, row: Referral, *,
                       now: datetime | None = None) -> bool:
    """Pay a pending, unflagged referral once, within the referrer's monthly cap.
    True when this call paid it."""
    now = now or datetime.now(UTC)
    await ledger.lock_user(db, row.referrer_id)  # serializes this referrer's rewards
    await db.refresh(row)
    if row.status != "pending" or row.needs_review:
        return False
    paid = await db.scalar(select(func.count()).select_from(Referral).where(
        Referral.referrer_id == row.referrer_id, Referral.status == "rewarded",
        Referral.rewarded_at >= month_start(now)))
    if int(paid) >= config.referrals.monthly_cap:
        row.status, row.reason, row.decided_at = "rejected", "over_monthly_cap", now
        await db.flush()
        return False
    reward, invitee = config.referrals.reward_credits, config.referrals.invitee_reward_credits
    await ledger.grant(db, row.referrer_id, reward, reason="referral", idempotency_key=f"referral:{row.id}",
                       reference_id=str(row.id), note="friend joined")
    if invitee:
        await ledger.grant(db, row.referee_id, invitee, reason="referral",
                           idempotency_key=f"referral-invitee:{row.id}", reference_id=str(row.id),
                           note="welcome credit")
    row.status, row.rewarded_at, row.reward_credits, row.invitee_credits = "rewarded", now, reward, invitee
    await db.flush()
    log.info("referral rewarded id=%s referrer=%s credits=%d", row.id, row.referrer_id, reward)
    return True


async def on_first_tailoring(db: AsyncSession, config: BillingConfig, user_id: uuid.UUID) -> bool:
    """The trigger for on_first_tailoring: the referee finished a tailoring."""
    if not config.referrals.enabled or config.referrals.trigger != "on_first_tailoring":
        return False
    row = await db.scalar(select(Referral).where(Referral.referee_id == user_id, Referral.status == "pending"))
    return row is not None and await maybe_reward(db, config, row)


# --- admin queue ------------------------------------------------------------------------------


class NotAllowed(Exception):
    """The referral isn't in a state that allows this action."""


async def approve(db: AsyncSession, config: BillingConfig, referral_id: uuid.UUID, admin_id: uuid.UUID) -> Referral:
    """Clear a flagged referral. It pays now if its trigger already fired (or fires later)."""
    row = await db.get(Referral, referral_id, with_for_update=True)
    if row is None or row.status != "pending" or not row.needs_review:
        raise NotAllowed()
    row.needs_review, row.decided_at, row.decided_by = False, datetime.now(UTC), admin_id
    await db.flush()
    fired = config.referrals.trigger == "on_verified_signup" or await _referee_has_tailored(db, row.referee_id)
    if fired:
        await maybe_reward(db, config, row)
    return row


async def reject(db: AsyncSession, referral_id: uuid.UUID, admin_id: uuid.UUID, reason: str) -> Referral:
    row = await db.get(Referral, referral_id, with_for_update=True)
    if row is None or row.status != "pending":
        raise NotAllowed()
    row.status, row.reason, row.needs_review = "rejected", reason, False
    row.decided_at, row.decided_by = datetime.now(UTC), admin_id
    await db.flush()
    return row


async def reverse(db: AsyncSession, referral_id: uuid.UUID, admin_id: uuid.UUID, reason: str) -> Referral:
    """Undo a paid referral: take the credits back (never below zero) and reject it."""
    row = await db.get(Referral, referral_id, with_for_update=True)
    if row is None or row.status != "rewarded":
        raise NotAllowed()
    await ledger.take_back(db, row.referrer_id, row.reward_credits, reason="referral",
                           idempotency_key=f"referral-reversal:{row.id}", reference_id=str(row.id), note=reason)
    if row.invitee_credits:
        await ledger.take_back(db, row.referee_id, row.invitee_credits, reason="referral",
                               idempotency_key=f"referral-invitee-reversal:{row.id}", reference_id=str(row.id),
                               note=reason)
    now = datetime.now(UTC)
    row.status, row.reason, row.reversed_at, row.decided_at, row.decided_by = "rejected", reason, now, now, admin_id
    await db.flush()
    log.info("referral reversed id=%s referrer=%s", row.id, row.referrer_id)
    return row


async def _referee_has_tailored(db: AsyncSession, user_id: uuid.UUID) -> bool:
    return await db.scalar(select(Analysis.id).where(Analysis.user_id == user_id, Analysis.tailored_at.is_not(None))
                           .limit(1)) is not None
