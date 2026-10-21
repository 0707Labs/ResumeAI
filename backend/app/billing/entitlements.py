"""Entitlement decisions: pure functions over a snapshot of what a user has.

Tailoring is free to try and paid at download, so there are two questions:

can_start_tailoring: may this user start another tailoring? The monthly free allowance
first, then an active pass under its fair-use cap, then Pro under its cap, then a credit
balance that would cover one download. Starting never spends a credit. Nothing left
means 'no_credits' (HTTP 402, the pricing dialog).

can_user_run: may this user take a paid action (downloading the clean file) now? An
active pass, active Pro, or a credit balance of at least credits_per_download. The
download spends the credit; this only decides.

The snapshot is loaded by app.billing.analyses while it holds the user's row lock, so
two concurrent starts can't both see the last free run or the last unit of a cap.
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
    # Left after this: free runs, or pass / Pro runs; for "credit", the credit balance.
    remaining: int | None = None
    reason: Literal["no_credits"] | None = None


def can_start_tailoring(snap: Snapshot) -> Decision:
    free_left = snap.free_allowance - snap.free_used
    if free_left > 0:
        return Decision(True, "free", remaining=free_left - 1)
    for p in snap.passes:
        if p.left > 0:
            return Decision(True, "pass", pass_id=p.id, remaining=p.left - 1)
    if snap.pro is not None and snap.pro.left > 0:
        return Decision(True, "pro", subscription_id=snap.pro.id, remaining=snap.pro.left - 1)
    if snap.credits >= snap.credits_per_download:
        return Decision(True, "credit", remaining=snap.credits)  # spends nothing now
    return Decision(False, None, remaining=0, reason="no_credits")


def can_user_run(snap: Snapshot) -> Decision:
    """The paid-action check (download). Fair-use caps limit tailorings, not downloads."""
    if snap.passes:
        return Decision(True, "pass", pass_id=snap.passes[0].id)
    if snap.pro is not None:
        return Decision(True, "pro", subscription_id=snap.pro.id)
    if snap.credits >= snap.credits_per_download:
        return Decision(True, "credit", remaining=snap.credits - snap.credits_per_download)
    return Decision(False, None, remaining=0, reason="no_credits")
