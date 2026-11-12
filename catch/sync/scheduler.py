from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from catch.core.config import settings
from catch.core.db import get_session
from catch.sync import state

logger = logging.getLogger("catch.scheduler")

SOURCES = ("garmin", "withings", "concept2", "whoop")
FIT_DIR = Path(settings.db_file).parent / "fit"

_locks = {source: threading.Lock() for source in SOURCES}
_scheduler: BackgroundScheduler | None = None


def run_sync(source: str, days: int = 3) -> dict:
    lock = _locks[source]
    if not lock.acquire(blocking=False):
        return {"source": source, "skipped": "already running"}
    try:
        with get_session() as session:
            if source == "whoop":
                from catch.core.models import OAuthToken

                # Not connected is the normal state of a fresh install: no attempt, no error, no alert.
                if session.get(OAuthToken, "whoop") is None:
                    return {"source": source, "skipped": "not connected"}
            state.record_attempt(session, source)
            try:
                if source == "garmin":
                    from catch.sync.garmin_client import GarminClient

                    client = GarminClient(session)
                    start = date.today().fromordinal(date.today().toordinal() - days)
                    end = date.today()
                    result = {
                        "health_rows": client.sync_health(start, end),
                        "activities": client.sync_activities(start, end, FIT_DIR),
                        "weight_rows": client.sync_weight(start, end),
                    }
                elif source == "withings":
                    from catch.sync.withings_client import sync as withings_sync

                    from catch.core.models import SyncState

                    row = session.get(SyncState, "withings")
                    cursor = int(row.cursor) if row and row.cursor else None
                    n = withings_sync(session, lastupdate=cursor)
                    result = {"measures": n}
                elif source == "concept2":
                    from catch.sync.concept2_client import sync as concept2_sync

                    from catch.core.models import SyncState

                    row = session.get(SyncState, "concept2")
                    updated_after = (
                        datetime.fromtimestamp(int(row.cursor), tz=timezone.utc) if row and row.cursor else None
                    )
                    result = concept2_sync(session, updated_after=updated_after, days=days)
                elif source == "whoop":
                    from catch.sync.whoop_client import sync as whoop_sync

                    result = {"records": whoop_sync(session, days=days)}
                else:
                    raise ValueError(f"unknown source: {source}")
                state.record_success(session, source, cursor=str(int(datetime.now(timezone.utc).timestamp())))
                from catch.sync.scoring import recompute_scores

                recompute_scores(session)
                if source == "garmin":
                    _post_garmin_enrichment(session)
                return {"source": source, **result}
            except Exception as exc:
                logger.exception("sync failed for %s", source)
                state.record_error(session, source, str(exc))
                return {"source": source, "error": str(exc)}
    finally:
        lock.release()


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


def start_scheduler() -> BackgroundScheduler:
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
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
