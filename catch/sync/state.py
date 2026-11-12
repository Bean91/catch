from __future__ import annotations

from catch.core import tenant
from datetime import datetime, timezone

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


def record_success(session: Session, source: str, cursor: str | None = None) -> None:
    row = session.get(SyncState, tenant.pk(source))
    if row is None:
        row = SyncState(source=source)
        session.add(row)
    row.last_success_at = datetime.now(timezone.utc)
    row.last_error = None
    row.consecutive_failures = 0
    row.alert_sent_at = None  # episode over, win or lose — see triggers.py's docstrings
    if cursor is not None:
        row.cursor = cursor
    session.commit()
    if not tenant.is_public():  # one shared dead-man's-switch means nothing across many users
        from catch.core.healthchecks import ping_sync_ok

        ping_sync_ok()


def record_error(session: Session, source: str, error: str) -> None:
    row = session.get(SyncState, tenant.pk(source))
    if row is None:
        row = SyncState(source=source)
        session.add(row)
    error = redact(error)  # httpx errors carry the request URL, which can hold a key
    row.last_error = error
    row.consecutive_failures = (row.consecutive_failures or 0) + 1
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
