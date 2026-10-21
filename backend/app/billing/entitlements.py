"""Which entitlement pays for a new analysis: a pure decision over a snapshot.

Order: an active pass under its fair-use cap, then Pro under its cap, then credits,
then the monthly free allowance. Nothing left means 'no_credits' (HTTP 402).

The snapshot is loaded by app.billing.analyses while it holds the user's row lock, so
two concurrent starts can't both see the last free run or the last unit of a cap.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

PaysWith = Literal["pass", "pro", "credit", "free"]


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
    credits_per_analysis: int


@dataclass(frozen=True)
class Decision:
    allowed: bool
    pays_with: PaysWith | None
    pass_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    credits: int = 0  # charged for this run
    remaining: int | None = None  # left on what paid, after this run
    reason: Literal["no_credits"] | None = None


def can_user_run(snap: Snapshot) -> Decision:
    for p in snap.passes:
        if p.left > 0:
            return Decision(True, "pass", pass_id=p.id, remaining=p.left - 1)
    if snap.pro is not None and snap.pro.left > 0:
        return Decision(True, "pro", subscription_id=snap.pro.id, remaining=snap.pro.left - 1)
    if snap.credits >= snap.credits_per_analysis:
        return Decision(True, "credit", credits=snap.credits_per_analysis,
                        remaining=snap.credits - snap.credits_per_analysis)
    free_left = snap.free_allowance - snap.free_used
    if free_left > 0:
        return Decision(True, "free", remaining=free_left - 1)
    return Decision(False, None, remaining=0, reason="no_credits")
