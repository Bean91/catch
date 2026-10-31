from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session

from catch.core.models import SyncState


def record_attempt(session: Session, source: str) -> None:
    row = session.get(SyncState, source)
    if row is None:
        row = SyncState(source=source)
        session.add(row)
    row.last_attempt_at = datetime.now(timezone.utc)
    session.commit()


def record_success(session: Session, source: str, cursor: str | None = None) -> None:
    row = session.get(SyncState, source)
    if row is None:
        row = SyncState(source=source)
        session.add(row)
    row.last_success_at = datetime.now(timezone.utc)
    row.last_error = None
    if cursor is not None:
        row.cursor = cursor
    session.commit()


def record_error(session: Session, source: str, error: str) -> None:
    row = session.get(SyncState, source)
    if row is None:
        row = SyncState(source=source)
        session.add(row)
    row.last_error = error
    session.commit()
