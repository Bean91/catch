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
JOBS = ("sync", "notifications", "retention")


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


def _retention_work() -> None:
    from catch.sync import account_store, retention

    with Session(db_module.engine) as session:
        retention.prune_owner(session)
    account_store.prune_global()  # global tables: idempotent, so running it once per user is harmless


@router.post("/tick/{job}")
def tick(job: str):
    if job not in JOBS:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job}")
    # Looked up by name at call time (not bound in a dict at import) so a test can substitute one job's work.
    work = {"sync": "_sync_work", "notifications": "_notification_work", "retention": "_retention_work"}[job]
    return run_for_each_user(job, globals()[work])


@router.get("/db-check")
def db_check():
    """Run this from the deployed app: it is the only place the pooler path and egress can really be tested."""
    from catch.core import db_pg

    report = db_pg.role_report(db_module.engine)
    return {**report, **db_pg.rls_probe(db_module.engine), "pool_mode": settings.db_pool_mode, **db_pg.schema_revision(db_module.engine)}


# Settings an operator sets by hand, as (environment name, Settings attribute). Reported as set/unset only — a value never leaves the process.
# SUPABASE_SECRET_KEY is deliberately absent: exactly one module may read it (tests/tenancy/test_structure.py); account deletion proves it.
_CHECKED = (
    ("DATABASE_URL", "database_url"), ("SUPABASE_URL", "supabase_url"), ("SUPABASE_PUBLISHABLE_KEY", "supabase_publishable_key"),
    ("CATCH_SECRETS_MASTER_KEY", "secrets_master_key"), ("CATCH_TICK_SECRET", "tick_secret"),
    ("CATCH_MODERATOR_IDS", "moderator_ids"), ("VAPID_PUBLIC_KEY", "vapid_public_key"), ("VAPID_PRIVATE_KEY", "vapid_private_key"),
    ("WHOOP_CLIENT_ID", "whoop_client_id"), ("WHOOP_CLIENT_SECRET", "whoop_client_secret"), ("WHOOP_REDIRECT_URI", "whoop_redirect_uri"),
    ("WITHINGS_CLIENT_ID", "withings_client_id"), ("WITHINGS_CLIENT_SECRET", "withings_client_secret"), ("WITHINGS_REDIRECT_URI", "withings_redirect_uri"),
    ("CONCEPT2_CLIENT_ID", "concept2_client_id"), ("CONCEPT2_CLIENT_SECRET", "concept2_client_secret"), ("CONCEPT2_REDIRECT_URI", "concept2_redirect_uri"),
    # Session 30 (native apps): set/unset only, like everything here.
    ("CATCH_APPLE_TEAM_ID", "apple_team_id"), ("CATCH_ANDROID_CERT_SHA256", "android_cert_sha256"),
    ("APNS_KEY_P8", "apns_key_p8"), ("APNS_KEY_ID", "apns_key_id"), ("APNS_TEAM_ID", "apns_team_id"), ("FCM_SERVICE_ACCOUNT_JSON", "fcm_service_account_json"),
)
_REDIRECTS = {"WHOOP_REDIRECT_URI": ("whoop_redirect_uri", "whoop"), "WITHINGS_REDIRECT_URI": ("withings_redirect_uri", "withings"), "CONCEPT2_REDIRECT_URI": ("concept2_redirect_uri", "concept2")}


@router.get("/config-check")
def config_check():
    """Which operator settings the *running* process actually sees. Environment listings show what was saved, not what the deployed
    instance loaded; this answers "is X set?" without printing a value. A redirect URI is also compared with the callback this
    deployment expects (a provider rejects the authorize step on any difference)."""
    from catch.sync import providers

    out = {name: bool(getattr(settings, attr)) for name, attr in _CHECKED}
    base = settings.base_url.rstrip("/")
    redirects = {name: getattr(settings, attr) == f"{base}/auth/{provider}/callback" for name, (attr, provider) in _REDIRECTS.items() if getattr(settings, attr)}
    return {
        "set": out,
        "redirect_matches_expected": redirects,
        "providers_available": {p: providers.available(p) for p in ("garmin", "withings", "concept2", "whoop")},
        "providers_oauth_available": {p: providers.oauth_available(p) for p in ("withings", "concept2", "whoop")},
        "base_url_is_https": settings.base_url.startswith("https://"),
    }
