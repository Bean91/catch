"""A cross-replica "this is already running" claim, shared by the tick (per user, per job) and by every provider sync.

The in-process lock in scheduler.py only covers one process; FastAPI Cloud can run replicas, and a manual sync can overlap a tick.
The claim is a `sync_state` row named `job:<name>` taken under a transaction-scoped advisory lock (safe behind a pooler); the row is
what spans the job's own commits. Only the Postgres deployment needs it — the Pi has exactly one process."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlmodel import Session

from catch.core import tenant, tenant_hooks
from catch.core.models import SyncState

LEASE = timedelta(minutes=10)


def claim(session: Session, job: str) -> bool:
    if tenant_hooks.uses_rls(session.get_bind()):
        session.connection().execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"catch:{job}:{tenant.current_owner()}"})
    key = f"job:{job}"
    now = datetime.now(timezone.utc)
    row = session.get(SyncState, tenant.pk(key))
    if row is None:
        row = SyncState(source=key)
        session.add(row)
    elif row.last_attempt_at is not None:
        started = row.last_attempt_at if row.last_attempt_at.tzinfo else row.last_attempt_at.replace(tzinfo=timezone.utc)
        finished = row.last_success_at
        running = finished is None or finished < row.last_attempt_at
        if running and now - started < LEASE:
            session.rollback()
            return False
    row.last_attempt_at = now
    session.commit()
    return True


def finish(session: Session, job: str) -> None:
    """Release. Called whether the job succeeded or failed: the lease means 'running', not 'succeeded'."""
    row = session.get(SyncState, tenant.pk(f"job:{job}"))
    if row is not None:
        row.last_success_at = datetime.now(timezone.utc)
        session.commit()
