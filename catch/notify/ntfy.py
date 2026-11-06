from __future__ import annotations

import logging

import httpx

from catch.core.config import settings

logger = logging.getLogger("catch.notify.ntfy")

_NTFY_BASE = "https://ntfy.sh"


def send(message: str) -> bool:
    """Task Part B.3's second ops-alert channel — a plain POST to a topic, no account, no
    auth. A no-op (returns False) whenever NTFY_TOPIC is unset, same "blank disables it, never
    errors" convention as the healthchecks pings. Best-effort: a failure here must never block
    or fail the sync/alert path that called it, so every error is caught and logged, not
    raised."""
    if not settings.ntfy_topic:
        return False
    try:
        resp = httpx.post(f"{_NTFY_BASE}/{settings.ntfy_topic}", content=message.encode(), timeout=10.0)
        resp.raise_for_status()
        return True
    except httpx.HTTPError:
        logger.exception("ntfy send failed")
        return False
