"""Verifier counts kept on each analysis for /admin/quality. Counts only, never text."""

from app.models.tailor import ReviewStatus, TailoredResume


def _flagged(bullet) -> bool:
    return bool(bullet.verification and bullet.verification.flags)


def tailor_counts(result: TailoredResume) -> dict[str, int]:
    """When a tailoring finishes: bullets produced, rewrites the verifier blocked, and
    bullets carrying a warning for the user to look at."""
    return {"bullets_generated": len(result.bullets), "bullets_blocked": result.blocked_rewrites,
            "bullets_flagged": sum(1 for b in result.bullets if _flagged(b))}


def download_counts(checked: TailoredResume) -> dict[str, int]:
    """At a paid download, from the re-verified tailoring: what the user approved and
    rejected, and how many approved bullets still carried a warning (an override)."""
    approved = [b for b in checked.bullets if b.review == ReviewStatus.APPROVED]
    return {"bullets_approved": len(approved),
            "bullets_rejected": sum(1 for b in checked.bullets if b.review == ReviewStatus.REJECTED),
            "flag_overrides": sum(1 for b in approved if _flagged(b))}
