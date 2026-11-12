"""Session 24 (docs/public-architecture.md §5): operator endpoints for the public deployment.

FastAPI Cloud documents no scheduler and may scale to zero, so scheduled work is a tick that an external cron
(Supabase pg_cron + pg_net, or any HTTP cron) calls with a shared secret. The tick walks users one at a time under
that user's own context; a per-(user, job) lease row keeps overlapping ticks from running the same work twice."""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlmodel import Session, select

from catch.core import db as db_module
from catch.core import tenant, tenant_hooks
from catch.core.config import settings
from catch.core.models import SyncState, UserProfile

logger = logging.getLogger("catch.tick")
LEASE = timedelta(minutes=10)
JOBS = ("sync", "notifications")


def require_tick_secret(request: Request) -> None:
    if not tenant.is_public() or not settings.tick_secret:
        raise HTTPException(status_code=404)
    header = request.headers.get("authorization", "")
    given = header[len("bearer ") :].strip() if header.lower().startswith("bearer ") else ""
    if not given or not hmac.compare_digest(given.encode(), settings.tick_secret.encode()):
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/internal", dependencies=[Depends(require_tick_secret)])


def user_ids() -> list[str]:
    with tenant.system(), Session(db_module.engine) as session:
        if tenant_hooks.uses_rls(db_module.engine):
            rows = session.connection().execute(text("SELECT catch_private.list_user_ids()")).scalars().all()
            session.rollback()
            return list(rows)
        return list(session.exec(select(UserProfile.id).execution_options(tenant_unscoped=True)).all())


def _claim(session: Session, job: str) -> bool:
    """Take the lease for (this user, job). The advisory lock is transaction-scoped (safe behind a pooler) and
    only serialises the claim itself; the lease row is what spans the job's own commits."""
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


def _finish(session: Session, job: str) -> None:
    row = session.get(SyncState, tenant.pk(f"job:{job}"))
    if row is not None:
        row.last_success_at = datetime.now(timezone.utc)
        session.commit()


def run_for_each_user(job: str, work: Callable[[], object]) -> dict:
    summary = {"users": 0, "ran": 0, "skipped_running": 0, "failed": 0}
    for uid in user_ids():
        summary["users"] += 1
        with tenant.use_owner(uid):
            with Session(db_module.engine) as session:
                if not _claim(session, job):
                    summary["skipped_running"] += 1
                    continue
            try:
                work()
                with Session(db_module.engine) as session:
                    _finish(session, job)
                summary["ran"] += 1
            except Exception:  # noqa: BLE001 — one user's failure never stops the others; no user data is logged
                logger.exception("tick job %s failed for one user", job)
                summary["failed"] += 1
    return summary


def _sync_work() -> None:
    from catch.sync.scheduler import SOURCES, run_sync

    for source in SOURCES:
        run_sync(source)


def _notification_work() -> None:
    from catch.sync.scheduler import check_notifications

    check_notifications()


@router.post("/tick/{job}")
def tick(job: str):
    if job not in JOBS:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job}")
    return run_for_each_user(job, _sync_work if job == "sync" else _notification_work)


@router.get("/db-check")
def db_check():
    """Run this from the deployed app: it is the only place the pooler path and egress can really be tested."""
    from catch.core import db_pg

    report = db_pg.role_report(db_module.engine)
    return {**report, **db_pg.rls_probe(db_module.engine), "pool_mode": settings.db_pool_mode}
