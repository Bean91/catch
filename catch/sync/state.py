from __future__ import annotations

from catch.core import tenant
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from catch.core.models import SyncState
from catch.core.redact import redact


def record_attempt(session: Session, source: str) -> None:
    row = session.get(SyncState, tenant.pk(source))
    if row is None:
        row = SyncState(source=source)
        session.add(row)
    row.last_attempt_at = datetime.now(timezone.utc)
    session.commit()


_CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 3
BACKOFF_BASE_S = 300
BACKOFF_CAP_S = 6 * 3600


def backoff_seconds(failures: int, retry_after: float | None = None) -> float:
    """5 min, 10, 20 … capped at 6 h; a provider's own Retry-After wins when it asks for longer."""
    exp = min(BACKOFF_BASE_S * (2 ** max(failures - 1, 0)), BACKOFF_CAP_S)
    return max(exp, min(retry_after or 0, BACKOFF_CAP_S))


def backoff_active(session: Session, source: str) -> bool:
    row = session.get(SyncState, tenant.pk(source))
    if row is None or row.next_attempt_at is None:
        return False
    due = row.next_attempt_at if row.next_attempt_at.tzinfo else row.next_attempt_at.replace(tzinfo=timezone.utc)
    return due > datetime.now(timezone.utc)


def record_success(session: Session, source: str, cursor: str | None = None) -> None:
    row = session.get(SyncState, tenant.pk(source))
    if row is None:
        row = SyncState(source=source)
        session.add(row)
    row.last_success_at = datetime.now(timezone.utc)
    row.last_error = None
    row.consecutive_failures = 0
    row.alert_sent_at = None  # episode over, win or lose — see triggers.py's docstrings
    row.next_attempt_at = None
    if cursor is not None:
        row.cursor = cursor
    session.commit()
    if not tenant.is_public():  # one shared dead-man's-switch means nothing across many users
        from catch.core.healthchecks import ping_sync_ok

        ping_sync_ok()


def record_error(session: Session, source: str, error: str, *, retry_after: float | None = None) -> None:
    row = session.get(SyncState, tenant.pk(source))
    if row is None:
        row = SyncState(source=source)
        session.add(row)
    error = redact(error)  # httpx errors carry the request URL, which can hold a key
    row.last_error = error
    row.consecutive_failures = (row.consecutive_failures or 0) + 1
    row.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds(row.consecutive_failures, retry_after))
    session.commit()
    # Edge-triggered on the exact failure that crosses the threshold, not every failure past
    # it — "fires once, not repeatedly" (task's quality bar) for a single broken episode.
    # `alert_sent_at` only gets set when the send actually went out (see triggers.py's
    # `alert_sync_broken`) — a send suppressed by quiet hours leaves it unset, so the *next*
    # failed attempt (consecutive_failures keeps climbing past 3) tries again.
    if row.consecutive_failures >= _CONSECUTIVE_FAILURE_ALERT_THRESHOLD and row.alert_sent_at is None:
        from catch.notify.triggers import alert_sync_broken

        sent = alert_sync_broken(session, source, f"failed {row.consecutive_failures} times in a row: {error}")
        if sent:
            row.alert_sent_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()


def record_auth_failure(session: Session, source: str, error: str) -> None:
    """The provider refused the credential: retrying can't help, so there's no backoff to wait out — the connection is marked
    needs-reconnect and scheduled runs stop until the user reconnects. The user is told once (the same `sync_broken` push), not
    after three more doomed attempts."""
    row = session.get(SyncState, tenant.pk(source))
    if row is None:
        row = SyncState(source=source)
        session.add(row)
    row.last_error = redact(error)
    row.next_attempt_at = None
    session.commit()
    if row.alert_sent_at is None:
        from catch.notify.triggers import alert_sync_broken

        if alert_sync_broken(session, source, f"needs to be reconnected: {row.last_error}"):
            row.alert_sent_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()


def defer(session: Session, source: str, seconds: float) -> None:
    """Push the next *scheduled* attempt out without touching the failure counters (a throttled history import isn't a broken sync)."""
    row = session.get(SyncState, tenant.pk(source))
    if row is None:
        return
    row.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    session.commit()
