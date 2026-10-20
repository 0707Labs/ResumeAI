"""Who a verified sign-in identity belongs to. Shared by magic link, Google and GitHub.

Rules:
1. A known (provider, provider_account_id) is that account's user.
2. Otherwise a *verified* email equal to a live user's email links this identity
   to that user. Nothing unverified ever links.
3. Otherwise there is no user: the caller starts the invite gate.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.events import log_auth_event
from app.db.models import Account, User

Provider = Literal["google", "github", "email"]


@dataclass(frozen=True)
class Resolved:
    user: User | None
    linked: bool = False  # True when rule 2 just added an account


class AccountUnavailable(Exception):
    """The identity belongs to a suspended or deleted account."""

    def __init__(self, user_id: uuid.UUID):
        self.user_id = user_id


async def resolve_identity(
    db: AsyncSession, provider: Provider, provider_account_id: str, verified_email: str | None
) -> Resolved:
    """Apply the rules above. Commits when it links an account."""
    user = (await db.execute(
        select(User).join(Account, Account.user_id == User.id).where(
            Account.provider == provider, Account.provider_account_id == provider_account_id
        )
    )).scalar_one_or_none()
    if user is None and verified_email:
        user = (await db.execute(
            select(User).where(User.email == verified_email, User.deleted_at.is_(None))
        )).scalar_one_or_none()
        if user is not None:
            _check_usable(user)
            db.add(Account(
                user_id=user.id, provider=provider,
                provider_account_id=provider_account_id, email_at_link=verified_email,
            ))
            await db.commit()
            log_auth_event("account_linked_auto", user_id=user.id, provider=provider)
            return Resolved(user=user, linked=True)
    if user is not None:
        _check_usable(user)
    return Resolved(user=user)


def _check_usable(user: User) -> None:
    if user.status != "active" or user.deleted_at is not None:
        raise AccountUnavailable(user.id)
