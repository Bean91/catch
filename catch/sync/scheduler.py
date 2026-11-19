from __future__ import annotations

from catch.core import tenant
import logging
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from catch.core.config import settings
from catch.core.db import get_session
from catch.sync import state

logger = logging.getLogger("catch.scheduler")

SOURCES = ("garmin", "withings", "concept2", "whoop")
FIT_DIR = Path(settings.db_file).parent / "fit"
BACKFILL_WINDOW_DAYS = 30  # Garmin rate-limits long pulls hard; the other providers use the same step for simplicity

_locks: dict[tuple[str, str], threading.Lock] = {}  # per (owner, source): one user's sync must not block another's
_locks_guard = threading.Lock()
_scheduler: BackgroundScheduler | None = None


def _lock_for(owner: str, source: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault((owner, source), threading.Lock())


def _skip(source: str, why: str) -> dict:
    return {"source": source, "skipped": why}


def _refresh_club_challenges(session) -> None:
    """New data can change a member's challenge standing, so recompute it here (as them) rather than on a timer. Public deployment only; a bug in
    this newer subsystem must not undo a finished sync."""
    if not tenant.is_public():
        return
    try:
        from catch.sync.club_challenges import refresh_my_scores

        refresh_my_scores(session)
    except Exception:
        logger.exception("club challenge refresh failed")
        session.rollback()


def run_sync(source: str, days: int = 3, *, manual: bool = False) -> dict:
    """One provider, for the current owner. Credentials are resolved here from the owner's own connection — nothing secret is ever
    a parameter. A scheduled run skips a connection that needs reconnecting or is backing off; a manual one always tries."""
    from catch.sync import connections, lease
    from catch.sync.providers import available
    from catch.sync.providers.base import ProviderAuthError, ProviderRateLimited

    if source not in SOURCES:
        raise ValueError(f"unknown source: {source}")
    if tenant.is_public() and source == "garmin" and not available("garmin"):
        return _skip(source, "not available on this server")
    local = _lock_for(tenant.current_owner(), source)
    if not local.acquire(blocking=False):
        return _skip(source, "already running")
    claimed = False
    try:
        with get_session() as session:
            # Not connected is the normal state of a fresh account: no attempt, no error, no alert.
            conn = connections.get(session, source)
            if conn is None:
                return _skip(source, "not connected")
            if not manual and conn.status == connections.NEEDS_RECONNECT:
                return _skip(source, "needs reconnect")
            if not manual and state.backoff_active(session, source):
                return _skip(source, "backing off")
            if tenant.is_public():
                if not lease.claim(session, f"sync:{source}"):
                    return _skip(source, "already running")
                claimed = True
            state.record_attempt(session, source)
            try:
                result = _sync_provider(session, source, days)
                state.record_success(session, source, cursor=str(int(datetime.now(timezone.utc).timestamp())))
                connections.mark_ok(session, source)
                from catch.sync.scoring import recompute_scores

                recompute_scores(session)
                _refresh_club_challenges(session)
                if source == "garmin":
                    _post_garmin_enrichment(session)
                backfill = _advance_backfill(session, source)
                if backfill is not None:
                    result["backfill"] = backfill
                return {"source": source, **result}
            except ProviderAuthError as exc:
                logger.warning("sync for %s needs a reconnect", source)
                session.rollback()
                connections.mark(session, source, connections.NEEDS_RECONNECT, getattr(exc, "detail", "key_rejected"))
                state.record_auth_failure(session, source, str(exc))
                return {"source": source, "error": str(exc), "needs_reconnect": True}
            except ProviderRateLimited as exc:
                logger.warning("sync for %s was rate limited", source)
                session.rollback()
                connections.mark(session, source, connections.RATE_LIMITED, "rate_limited")
                state.record_error(session, source, str(exc), retry_after=exc.retry_after)
                return {"source": source, "error": str(exc), "rate_limited": True}
            except Exception as exc:
                logger.exception("sync failed for %s", source)
                session.rollback()
                connections.mark(session, source, connections.ERROR, "sync_failed")
                state.record_error(session, source, str(exc))
                return {"source": source, "error": str(exc)}
    finally:
        if claimed:
            try:
                with get_session() as session:
                    lease.finish(session, f"sync:{source}")
            except Exception:  # noqa: BLE001 — a stuck lease expires on its own after ten minutes
                logger.warning("couldn't release the sync lease for %s", source)
        local.release()


def _sync_provider(session, source: str, days: int) -> dict:
    from catch.core.models import SyncState

    if source == "garmin":
        from catch.sync.garmin_client import GarminClient

        client = GarminClient(session)
        start = date.today().fromordinal(date.today().toordinal() - days)
        end = date.today()
        return {
            "health_rows": client.sync_health(start, end),
            "activities": client.sync_activities(start, end, FIT_DIR),
            "weight_rows": client.sync_weight(start, end),
        }
    if source == "withings":
        from catch.sync.withings_client import sync as withings_sync

        row = session.get(SyncState, tenant.pk("withings"))
        cursor = int(row.cursor) if row and row.cursor else None
        return {"measures": withings_sync(session, lastupdate=cursor)}
    if source == "concept2":
        from catch.sync.concept2_client import sync as concept2_sync

        row = session.get(SyncState, tenant.pk("concept2"))
        updated_after = datetime.fromtimestamp(int(row.cursor), tz=timezone.utc) if row and row.cursor else None
        return concept2_sync(session, updated_after=updated_after, days=days)
    from catch.sync.whoop_client import sync as whoop_sync

    return {"records": whoop_sync(session, days=days)}


def start_backfill(session, source: str, days: int | None = None) -> None:
    """Called when a user connects a provider: queue the history import. It then runs one window per scheduled sync — never inside
    the request that connected the account, whose timeout is not ours to rely on."""
    from catch.core.models import SyncState
    from catch.sync import connections

    span = settings.backfill_days if days is None else days
    row = session.get(SyncState, tenant.pk(source))
    if row is None:
        row = SyncState(source=source)
        session.add(row)
    row.backfill_cursor = (date.today() - timedelta(days=span)).isoformat() if span > 0 else None
    session.commit()
    connections.mark_ok(session, source)


def _advance_backfill(session, source: str) -> dict | None:
    """Import the next history window, if one is queued. A failure leaves the cursor where it was (the next run retries the same
    window) and only defers; it never turns a good incremental sync into a failed one."""
    from catch.core.models import SyncState
    from catch.sync import connections
    from catch.sync.providers.base import ProviderAuthError, ProviderRateLimited

    row = session.get(SyncState, tenant.pk(source))
    if row is None or not row.backfill_cursor:
        return None
    try:
        cursor = date.fromisoformat(row.backfill_cursor)
    except ValueError:
        row.backfill_cursor = None
        session.commit()
        return None
    today = date.today()
    window_end = min(cursor + timedelta(days=BACKFILL_WINDOW_DAYS - 1), today)
    try:
        result = _sync_window(session, source, cursor, window_end)
    except ProviderAuthError:
        raise
    except ProviderRateLimited as exc:
        session.rollback()
        state.defer(session, source, state.backoff_seconds(1, exc.retry_after))
        return {"deferred": "rate_limited", "next_window_from": cursor.isoformat()}
    except Exception:  # noqa: BLE001
        logger.warning("history import window failed for %s", source, exc_info=True)
        session.rollback()
        state.defer(session, source, 1800)
        return {"deferred": "window_failed", "next_window_from": cursor.isoformat()}
    row = session.get(SyncState, tenant.pk(source))
    nxt = window_end + timedelta(days=1)
    row.backfill_cursor = None if nxt > today else nxt.isoformat()
    session.commit()
    connections.mark_ok(session, source)
    from catch.sync.scoring import recompute_scores

    recompute_scores(session)
    return {"window": [cursor.isoformat(), window_end.isoformat()], **result, "done": row.backfill_cursor is None}


def _sync_window(session, source: str, start: date, end: date) -> dict:
    if source == "garmin":
        from catch.sync.garmin_client import GarminClient

        client = GarminClient(session)
        return {
            "health_rows": client.sync_health(start, end),
            "activities": client.sync_activities(start, end, FIT_DIR),
            "weight_rows": client.sync_weight(start, end),
        }
    if source == "withings":
        from catch.sync.withings_client import sync as withings_sync

        return {"measures": withings_sync(session, window=(start, end))}
    if source == "concept2":
        from catch.sync.concept2_client import sync as concept2_sync

        return concept2_sync(session, window=(start, end))
    from catch.sync.whoop_client import sync as whoop_sync

    return {"records": whoop_sync(session, window=(start, end))}


def _post_garmin_enrichment(session) -> None:
    """Session 20: weather for GPS activities (routes are grouped at ingest). Its own try/except
    and run only after the sync is already recorded successful — a weather outage or bug must
    never mark a Garmin sync as failed."""
    try:
        from catch.sync.weather import enrich_pending

        enrich_pending(session)
    except Exception:
        logger.warning("weather enrichment failed", exc_info=True)
        session.rollback()


_NOTIFICATION_CHECKS = (
    "check_morning_brief",
    "check_illness",
    "check_garmin_key_expiring",
    "check_sync_stale",
    "check_test_reminder",
)


def check_notifications() -> None:
    """Session 16 (see PLAN.md Part A): runs all five push triggers every tick. Each one
    wrapped individually — same "one source's failure doesn't take down the others" shape as
    `run_sync` — since nothing about e.g. a bad test-reminder query should ever block the
    morning brief in the same tick."""
    from catch.notify import triggers

    with get_session() as session:
        for name in _NOTIFICATION_CHECKS:
            try:
                getattr(triggers, name)(session)
            except Exception:
                logger.exception("notification check failed: %s", name)


def run_retention() -> None:
    from sqlmodel import Session

    from catch.core import db as db_module
    from catch.sync import retention

    with Session(db_module.engine) as session:
        retention.prune_owner(session)


def start_scheduler() -> BackgroundScheduler | None:
    if tenant.is_public():
        # A scale-to-zero replica is not a scheduler and N replicas would run every job N times: scheduled work
        # is an authenticated tick endpoint (catch/api/routes_internal.py), run per user.
        return None
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    scheduler = BackgroundScheduler()
    for source in SOURCES:
        scheduler.add_job(
            run_sync,
            args=[source],
            trigger=IntervalTrigger(hours=settings.sync_interval_hours, jitter=300),
            id=f"sync-{source}",
            replace_existing=True,
        )
    # Every 10 minutes — frequent enough that the morning brief's 120-minute grace window
    # (catch/notify/triggers.py) always gets several chances, cheap enough (a handful of small
    # queries against a single-user DB) to not matter on a Pi 3.
    scheduler.add_job(
        check_notifications,
        trigger=IntervalTrigger(minutes=10, jitter=30),
        id="notifications",
        replace_existing=True,
    )
    scheduler.add_job(run_retention, trigger=IntervalTrigger(hours=24, jitter=1800), id="retention", replace_existing=True)
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
