from __future__ import annotations

import json
import math
import threading
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from catch.analytics.load import training_load
from catch.analytics.recovery import recovery_score
from catch.analytics.strain import session_strain, strain_band
from catch.core.models import Activity, DailyScore, DailyWellness, Note
from catch.core.settings_store import get_settings

_lock = threading.Lock()


def _ln_hrv(row: DailyWellness) -> float | None:
    if row.hrv_rmssd and row.hrv_rmssd > 0:
        return math.log(row.hrv_rmssd)
    return None


def _local_day_utc_range(day: date) -> tuple[datetime, datetime]:
    # date.today(), Garmin's calendarDate, and Note.date are all local-calendar days; a naive
    # datetime's .astimezone() is defined to assume the *system* local timezone, which gives
    # the correct UTC range for that local day (DST-correct) without a new dependency. This
    # only matches the athlete's day if the Pi's system timezone is set to their own.
    local_midnight = datetime(day.year, day.month, day.day)
    start_utc = local_midnight.astimezone(timezone.utc)
    end_utc = (local_midnight + timedelta(days=1)).astimezone(timezone.utc)
    return start_utc, end_utc


def _day_activities(session: Session, day: date) -> list[Activity]:
    start, end = _local_day_utc_range(day)
    rows = session.exec(select(Activity).where(Activity.start >= start, Activity.start < end)).all()
    # A linked Garmin<->Concept2 pair is one physical session — keep only the Concept2 side
    # (source of truth for erg metrics; already HR-enriched from Garmin where it had none).
    return [a for a in rows if not (a.source == "garmin" and a.linked_activity_id is not None)]


def _note_rpe(session: Session, day: date) -> int | None:
    notes = session.exec(select(Note).where(Note.date == day).order_by(Note.id)).all()
    rpes = [n.rpe for n in notes if n.rpe is not None]
    return rpes[-1] if rpes else None


def day_strain(session: Session, day: date, settings: dict) -> dict:
    activities = _day_activities(session, day)
    if not activities:
        return {"value": 0.0, "band": "light", "trimp_like": 0.0, "components": [], "explanation": "No sessions logged."}

    rpe = _note_rpe(session, day)
    max_hr = settings.get("max_hr")
    wellness = session.get(DailyWellness, day)
    resting_hr = wellness.resting_hr if wellness else None

    scores = []
    for activity in activities:
        duration_minutes = (activity.duration or 0) / 60.0
        result = session_strain(
            duration_minutes=duration_minutes,
            avg_hr=activity.avg_hr,
            resting_hr=resting_hr,
            max_hr=max_hr,
            rpe=rpe,
            settings=settings,
        )
        scores.append({"activity_id": activity.id, **result})

    total_trimp = sum(s["components"][0]["trimp_like"] for s in scores if s["value"] is not None)
    if total_trimp <= 0:
        return {
            "value": None,
            "band": "insufficient_data",
            "trimp_like": 0.0,
            "components": scores,
            "explanation": "No session that day had enough data (HR or an RPE note) to score.",
        }
    # Combine via the same log-saturation curve rather than summing 0-21 scores directly, so
    # several moderate sessions in one day don't just linearly stack toward "all out."
    combined = min(21.0, settings["strain_log_a"] * math.log1p(total_trimp))
    return {
        "value": combined,
        "band": strain_band(combined),
        "trimp_like": total_trimp,
        "components": scores,
        "explanation": f"{len(activities)} session(s) that day combined via log-saturation of total trimp_like={total_trimp:.1f}.",
    }


def day_recovery(session: Session, day: date, settings: dict, strain_cache: dict[date, float | None]) -> dict:
    wellness = session.get(DailyWellness, day)
    today_ln_hrv = _ln_hrv(wellness) if wellness else None
    today_rhr = wellness.resting_hr if wellness else None
    today_sleep = wellness.sleep_seconds if wellness else None

    history_start = day - timedelta(days=60)
    rows = session.exec(
        select(DailyWellness).where(DailyWellness.date >= history_start, DailyWellness.date < day).order_by(DailyWellness.date)
    ).all()
    hrv_history = [v for v in (_ln_hrv(r) for r in rows) if v is not None]
    rhr_history = [r.resting_hr for r in rows if r.resting_hr is not None]

    prior_day_strain = strain_cache.get(day - timedelta(days=1))

    return recovery_score(
        today_ln_hrv=today_ln_hrv,
        hrv_history_ln=hrv_history,
        today_resting_hr=today_rhr,
        rhr_history=rhr_history,
        today_sleep_seconds=today_sleep,
        prior_day_strain=prior_day_strain,
        settings=settings,
    )


def _earliest_date(session: Session) -> date | None:
    wellness_min = session.exec(select(DailyWellness.date).order_by(DailyWellness.date)).first()
    activity_min = session.exec(
        select(Activity.start).where(Activity.start.is_not(None)).order_by(Activity.start)
    ).first()
    # .date() alone takes the *UTC* calendar date, not the local one — for a few hours each
    # evening in a negative-UTC-offset timezone, the newest activity's UTC date is already
    # "tomorrow" while date.today() (local) is still "today". When that newest activity is
    # also the *earliest* one (a fresh DB, or this exact scenario in a test), this previously
    # computed an earliest date past today, so recompute_scores' day<=today loop silently
    # processed zero days. .astimezone() matches every other local-day computation in this
    # file (e.g. _local_day_utc_range) and in catch/api/routes_activities.py.
    candidates = [d for d in (wellness_min, activity_min.astimezone().date() if activity_min else None) if d]
    return min(candidates) if candidates else None


def recompute_scores(session: Session) -> int:
    """Recomputes every cached daily_scores row from scratch. Cheap at single-user scale
    (plain-Python arithmetic over a few thousand days at most) so there's no incremental
    path — simpler and avoids subtle staleness bugs when settings or history change."""
    if not _lock.acquire(blocking=False):
        return 0
    try:
        from catch.sync.concept2_client import relink_unmatched

        relink_unmatched(session)

        settings = get_settings(session)
        earliest = _earliest_date(session)
        if earliest is None:
            return 0

        lookback_days = settings["load_chronic_days"] * 2
        trimp_series: list[float] = []
        strain_cache: dict[date, float | None] = {}
        count = 0
        day = earliest
        today = date.today()
        while day <= today:
            strain = day_strain(session, day, settings)
            trimp_series.append(strain.get("trimp_like") or 0.0)
            strain_cache[day] = strain.get("value")

            load = training_load(trimp_series[-lookback_days:], settings)
            recovery = day_recovery(session, day, settings, strain_cache)

            row = session.get(DailyScore, day)
            if row is None:
                row = DailyScore(date=day)
                session.add(row)
            row.recovery_json = json.dumps(recovery)
            row.strain_json = json.dumps(strain)
            row.load_json = json.dumps(load)
            row.updated_at = datetime.now(timezone.utc)
            count += 1
            day += timedelta(days=1)

        session.commit()
        return count
    finally:
        _lock.release()
