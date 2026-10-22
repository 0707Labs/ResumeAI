"""A signed-in user's login methods, and account deletion.

- Linking needs proof of both sides: the session (this user) and the provider
  (or a magic link) for the new method. An identity already linked to someone
  else is never moved.
- Unlinking never removes the last login method; the user's rows are locked
  so two concurrent unlinks can't both pass the check.
- Deletion removes every linked provider record, session and pending sign-in
  for the user, withdraws their consents, and marks the user deleted. The purge
  job (later) hard-deletes after the grace period."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import delete, or_, select, text, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.signing import subject_ref
from app.db.models import (
    Account, AuthSession, ConsentRecord, EmailToken, JobPreferences, PendingAuth, SavedResume, User,
)
from app.db.rls import service_scope

Provider = Literal["google", "github", "email"]


class AccountError(Exception):
    """code: not_found | last_login_method | already_linked_elsewhere"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def list_accounts(db: AsyncSession, user_id: uuid.UUID) -> list[Account]:
    return list((await db.execute(
        select(Account).where(Account.user_id == user_id).order_by(Account.created_at)
    )).scalars())


async def link(db: AsyncSession, user: User, provider: Provider, provider_account_id: str,
               verified_email: str) -> Literal["linked", "already_linked"]:
    """Add a login method to `user`. Commits. Runs as the service role: whether another
    account already owns this identity or address is a question about other users' rows."""
    async with service_scope(db):
        return await _link(db, user, provider, provider_account_id, verified_email)


async def _link(db: AsyncSession, user: User, provider: Provider, provider_account_id: str,
                verified_email: str) -> Literal["linked", "already_linked"]:
    owner = (await db.execute(select(Account.user_id).where(
        Account.provider == provider, Account.provider_account_id == provider_account_id
    ))).scalar_one_or_none()
    if owner == user.id:
        return "already_linked"
    if owner is not None:
        raise AccountError("already_linked_elsewhere")
    if provider == "email":
        # Another live account signs in with this address; it can't be ours too.
        taken = (await db.execute(select(User.id).where(
            User.email == verified_email, User.deleted_at.is_(None), User.id != user.id
        ))).scalar_one_or_none()
        if taken is not None:
            raise AccountError("already_linked_elsewhere")
    db.add(Account(user_id=user.id, provider=provider, provider_account_id=provider_account_id,
                   email_at_link=verified_email))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AccountError("already_linked_elsewhere") from None
    return "linked"


async def unlink(db: AsyncSession, user_id: uuid.UUID, account_id: uuid.UUID) -> Provider:
    """Remove one login method, never the last. Commits; returns its provider."""
    rows = (await db.execute(
        select(Account).where(Account.user_id == user_id).with_for_update()
    )).scalars().all()
    target = next((a for a in rows if a.id == account_id), None)
    if target is None:
        await db.rollback()
        raise AccountError("not_found")
    if len(rows) <= 1:
        await db.rollback()
        raise AccountError("last_login_method")
    provider = target.provider
    await db.delete(target)
    await db.commit()
    return provider  # type: ignore[return-value]


async def delete_account(db: AsyncSession, user: User) -> None:
    """Delete the account and everything that lets anyone sign in to it. Commits.
    Runs as the service role: pending sign-ins and email tokens aren't user-owned rows."""
    async with service_scope(db):
        await _delete_account(db, user)


async def _delete_account(db: AsyncSession, user: User) -> None:
    uid, email, now = user.id, user.email, datetime.now(UTC)
    identities = [tuple(r) for r in (await db.execute(
        select(Account.provider, Account.provider_account_id).where(Account.user_id == uid)
    )).all()]
    if identities:
        await db.execute(delete(PendingAuth).where(
            tuple_(PendingAuth.provider, PendingAuth.provider_account_id).in_(identities)))
    await db.execute(delete(PendingAuth).where(PendingAuth.verified_email == email))
    await db.execute(delete(EmailToken).where(or_(EmailToken.user_id == uid, EmailToken.email == email)))
    await db.execute(delete(Account).where(Account.user_id == uid))
    # What the user wrote about themselves goes now too (the user row is only soft-deleted).
    await db.execute(delete(SavedResume).where(SavedResume.user_id == uid))  # versions cascade
    await db.execute(delete(JobPreferences).where(JobPreferences.user_id == uid))
    await db.execute(delete(AuthSession).where(AuthSession.user_id == uid))

    granted = (await db.execute(text(
        "SELECT purpose, notice_id FROM current_consents WHERE user_id = :u AND action = 'granted'"
    ), {"u": uid})).all()
    ref = subject_ref(email)
    db.add_all([ConsentRecord(user_id=uid, subject_ref=ref, notice_id=notice_id, purpose=purpose,
                              action="withdrawn", method="deletion") for purpose, notice_id in granted])
    await db.execute(update(User).where(User.id == uid).values(deleted_at=now))
    await db.commit()

