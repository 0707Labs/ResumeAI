"""Entitlement decisions: pure functions over a snapshot of what a user has.

Tailoring is free to try and paid at download, so there are two questions:

can_user_run: may this user take a paid action (download a clean file) now? An active
pass under its fair-use cap, then Pro under its cap, then a credit balance of at least
credits_per_download. Fair-use caps count paid downloads. The caller charges what this
picks; nothing left means 'no_credits' (HTTP 402, the pricing dialog).

can_start_tailoring: may this user start another tailoring? The monthly free
allowance first; past it, the same check as a download (so people who can't pay can't
run up AI costs). Starting never spends anything.

The snapshot is loaded by app.billing.analyses while it holds the user's row lock, so
two concurrent clicks can't both see the last free run, credit or unit of a cap.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

PaysWith = Literal["free", "pass", "pro", "credit"]


@dataclass(frozen=True)
class CapUsage:
    """A live pass or Pro subscription and how many of its runs count so far."""

    id: uuid.UUID
    used: int
    cap: int

    @property
    def left(self) -> int:
        return max(self.cap - self.used, 0)


@dataclass(frozen=True)
class Snapshot:
    credits: int
    passes: tuple[CapUsage, ...]  # live now, oldest first
    pro: CapUsage | None
    free_used: int
    free_allowance: int
    credits_per_download: int


@dataclass(frozen=True)
class Decision:
    allowed: bool
    pays_with: PaysWith | None
    pass_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    # Left after this: free tailorings, pass / Pro downloads, or credits. A tailoring
    # start spends nothing, so for it a pass, Pro or credit figure is what's left now.
    remaining: int | None = None
    reason: Literal["no_credits"] | None = None


def can_user_run(snap: Snapshot) -> Decision:
    for p in snap.passes:
        if p.left > 0:
            return Decision(True, "pass", pass_id=p.id, remaining=p.left - 1)
    if snap.pro is not None and snap.pro.left > 0:
        return Decision(True, "pro", subscription_id=snap.pro.id, remaining=snap.pro.left - 1)
    if snap.credits >= snap.credits_per_download:
        return Decision(True, "credit", remaining=snap.credits - snap.credits_per_download)
    return Decision(False, None, remaining=0, reason="no_credits")


def can_start_tailoring(snap: Snapshot) -> Decision:
    free_left = snap.free_allowance - snap.free_used
    if free_left > 0:
        return Decision(True, "free", remaining=free_left - 1)
    paid = can_user_run(snap)
    # Nothing is spent at start, so report the balance or cap as it stands.
    return paid if not paid.allowed else Decision(
        True, paid.pays_with, pass_id=paid.pass_id, subscription_id=paid.subscription_id,
        remaining=snap.credits if paid.pays_with == "credit" else (paid.remaining or 0) + 1)
