"""Session 24 (docs/public-architecture.md §5): operator endpoints for the public deployment.

FastAPI Cloud documents no scheduler and may scale to zero, so scheduled work is a tick that an external cron
(Supabase pg_cron + pg_net, or any HTTP cron) calls with a shared secret. The tick walks users one at a time under
that user's own context; a per-(user, job) lease row keeps overlapping ticks from running the same work twice."""

from __future__ import annotations

import hmac
import logging
import random
import time
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlmodel import Session, select

from catch.api.ratelimit import rate_limit
from catch.core import db as db_module
from catch.core import tenant, tenant_hooks
from catch.core.config import settings
from catch.core.models import UserProfile
from catch.sync import lease

logger = logging.getLogger("catch.tick")
TICK_BUDGET_S = 240.0  # stop starting new users after this long; the ones left run on the next tick
JOBS = ("sync", "notifications")


def require_tick_secret(request: Request) -> None:
    if not tenant.is_public() or not settings.tick_secret:
        raise HTTPException(status_code=404)
    header = request.headers.get("authorization", "")
    given = header[len("bearer ") :].strip() if header.lower().startswith("bearer ") else ""
    if not given or not hmac.compare_digest(given.encode(), settings.tick_secret.encode()):
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/internal", dependencies=[rate_limit("internal", by="ip"), Depends(require_tick_secret)])  # throttled first, so guessing the secret is metered


def user_ids() -> list[str]:
    with tenant.system(), Session(db_module.engine) as session:
        if tenant_hooks.uses_rls(db_module.engine):
            rows = session.connection().execute(text("SELECT catch_private.list_user_ids()")).scalars().all()
            session.rollback()
            return list(rows)
        return list(session.exec(select(UserProfile.id).execution_options(tenant_unscoped=True)).all())


def _claim(session: Session, job: str) -> bool:
    return lease.claim(session, job)


def _finish(session: Session, job: str) -> None:
    lease.finish(session, job)


def run_for_each_user(job: str, work: Callable[[], object], budget_s: float | None = None) -> dict:
    summary = {"users": 0, "ran": 0, "skipped_running": 0, "failed": 0, "deferred": 0}
    budget = TICK_BUDGET_S if budget_s is None else budget_s
    started = time.monotonic()
    uids = user_ids()
    random.shuffle(uids)  # a budget that runs out must not always starve the same users
    for uid in uids:
        summary["users"] += 1
        if time.monotonic() - started > budget:
            summary["deferred"] += 1
            continue
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
    """Credentials are resolved inside run_sync from this user's own connection row; the only things passed along are the source
    name and the owner context set by run_for_each_user."""
    from catch.sync.scheduler import SOURCES, run_sync

    for source in SOURCES:
        try:
            run_sync(source)
        except Exception:  # noqa: BLE001 — one provider never stops the others
            logger.exception("sync %s failed for one user", source)


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
