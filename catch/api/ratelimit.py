"""Route-level throttling on top of coach/limits.py's buckets. In-process and per replica (docs/security.md says so); the
ceilings are low enough on the sensitive buckets that N replicas still leave an attacker with a small multiple, and the DB-backed
counters (publishing, reports, export) cover the cases where that isn't acceptable."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from catch.coach import limits
from catch.core import tenant


def throttle(bucket: str, key: str | None = None) -> None:
    try:
        limits.check_rate(key or tenant.current_owner(), bucket)
    except limits.LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.message, headers={"Retry-After": str(exc.retry_after_s or 1)}) from None


def rate_limit(bucket: str, *, by: str = "owner"):
    """A dependency. `by="owner"` must run after authentication (put it on a router that already requires it); `by="ip"` is for
    the few unauthenticated routes, keyed on the socket peer (behind a shared proxy that is coarse, which is why those buckets
    are generous — the point there is to stop a flood, not to meter a person)."""

    def dependency(request: Request) -> None:
        key = f"ip:{request.client.host if request.client else 'unknown'}" if by == "ip" else None
        throttle(bucket, key)

    return Depends(dependency)
