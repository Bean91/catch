from __future__ import annotations

import logging

import httpx

from catch.core.config import settings

logger = logging.getLogger("catch.healthchecks")


def ping_sync_ok() -> None:
    """Task Part B.2: a dead-man's-switch ping after every successful sync. Pinged per
    individual source success (catch/sync/scheduler.py's `run_sync`), not once per "all three
    sources" cycle — the three sources run as independent APScheduler jobs on their own
    intervals/jitter, not as one combined cycle, so "after every successful sync cycle" is
    read as "after every successful sync." A no-op whenever HEALTHCHECKS_SYNC_URL is unset —
    never errors, never blocks the sync it's reporting on."""
    if not settings.healthchecks_sync_url:
        return
    try:
        httpx.get(settings.healthchecks_sync_url, timeout=10.0)
    except httpx.HTTPError:
        logger.exception("healthchecks sync ping failed")
