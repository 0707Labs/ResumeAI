"""In-process sliding-window rate limits for auth endpoints.

Fine while we run one API instance; move the counters to Redis before scaling
out. Keyed by client IP: uvicorn rewrites request.client from X-Forwarded-For
only for trusted proxies (127.0.0.1 by default, i.e. the Next.js rewrite)."""

import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request

from app.auth.events import log_auth_event


class SlidingWindow:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._hits: dict[str, deque[float]] = {}
        self._clock = clock

    def hit(self, key: str, limit: int, window: float) -> float | None:
        """Record a hit. Returns seconds to wait if over the limit, else None."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return hits[0] + window - now
        hits.append(now)
        if len(self._hits) > 10_000:  # drop idle keys so memory stays bounded
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - window}
        return None

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindow()


def rate_limit(name: str, limit: int, per_seconds: int):
    """FastAPI dependency: at most `limit` calls per client IP per window."""

    def check(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        wait = limiter.hit(f"{name}:{ip}", limit, per_seconds)
        if wait is not None:
            log_auth_event("rate_limited", outcome="denied", reason=name)
            raise HTTPException(
                status_code=429,
                detail="rate_limited",
                headers={"Retry-After": str(max(1, math.ceil(wait)))},
            )

    return check
