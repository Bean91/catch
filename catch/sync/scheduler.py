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

SOURCES = ("garmin", "withings", "concept2")
FIT_DIR = Path(settings.db_file).parent / "fit"

_locks = {source: threading.Lock() for source in SOURCES}
_scheduler: BackgroundScheduler | None = None


def run_sync(source: str, days: int = 3) -> dict:
    lock = _locks[source]
    if not lock.acquire(blocking=False):
        return {"source": source, "skipped": "already running"}
    try:
        with get_session() as session:
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
                else:
                    raise ValueError(f"unknown source: {source}")
                state.record_success(session, source, cursor=str(int(datetime.now(timezone.utc).timestamp())))
                from catch.sync.scoring import recompute_scores

                recompute_scores(session)
                return {"source": source, **result}
            except Exception as exc:
                logger.exception("sync failed for %s", source)
                state.record_error(session, source, str(exc))
                return {"source": source, "error": str(exc)}
    finally:
        lock.release()


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
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
