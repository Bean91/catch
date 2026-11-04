from __future__ import annotations

import json
import math
import threading
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from catch.analytics.load import training_load
from catch.analytics.recovery import recovery_score
from catch.analytics.strain import daily_activity_strain, session_strain, strain_band
from catch.core.models import Activity, CanonicalActivity, DailyScore, DailyWellness
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


def _overrides(canonical: CanonicalActivity) -> dict:
    return json.loads(canonical.overrides_json) if canonical.overrides_json else {}


def _day_activities(session: Session, day: date) -> list[CanonicalActivity]:
    """Session 8/12 (see PLAN.md): every reader of "an activity" for totals/strain/load now
    reads CanonicalActivity — the matching engine already guarantees one canonical per
    physical session, so nothing here needs its own Garmin<->Concept2 dedup logic anymore.
    A canonical with `exclude_from_totals` set (task Part C.1) is dropped entirely."""
    start, end = _local_day_utc_range(day)
    rows = session.exec(select(CanonicalActivity).where(CanonicalActivity.start >= start, CanonicalActivity.start < end)).all()
    return [a for a in rows if not _overrides(a).get("exclude_from_totals")]


def _note_rpe(session: Session, day: date) -> int | None:
    from catch.core.models import Note

    notes = session.exec(select(Note).where(Note.date == day).order_by(Note.id)).all()
    rpes = [n.rpe for n in notes if n.rpe is not None]
    return rpes[-1] if rpes else None


def _day_garmin_activity_totals(session: Session, day: date) -> tuple[int, float]:
    """Sum of steps/active-kcal already attributed to a Garmin-sourced activity that day —
    regardless of its canonical's `exclude_from_totals` flag, since the physical steps
    happened either way. Never a Concept2-only member: Concept2 never contributes to
    Garmin's own daily wellness totals, so there's nothing of its to double-subtract."""
    start, end = _local_day_utc_range(day)
    rows = session.exec(
        select(Activity).where(Activity.source == "garmin", Activity.start >= start, Activity.start < end)
    ).all()
    steps = sum(r.steps or 0 for r in rows)
    active_kcal = sum(max(0.0, (r.calories or 0.0) - (r.bmr_kcal or 0.0)) for r in rows)
    return steps, active_kcal


def _daily_activity_component(session: Session, day: date, settings: dict) -> dict:
    """Task Part A: non-exercise steps/active-kcal, added to strain's 0-21 `value` only
    (never `trimp_like`, so load/acute:chronic stay workout-only — see
    `catch.analytics.strain.daily_activity_strain`)."""
    wellness = session.get(DailyWellness, day)
    if wellness is None or wellness.steps is None:
        return daily_activity_strain(None, None, settings)
    exercise_steps, exercise_kcal = _day_garmin_activity_totals(session, day)
    non_exercise_steps = max(0, wellness.steps - exercise_steps)
    non_exercise_kcal = max(0.0, (wellness.active_kcal or 0.0) - exercise_kcal)
    return daily_activity_strain(non_exercise_steps, non_exercise_kcal, settings)


def day_strain(session: Session, day: date, settings: dict) -> dict:
    activities = _day_activities(session, day)
    if not activities:
        daily_activity = _daily_activity_component(session, day, settings)
        value = min(21.0, daily_activity["value"])
        return {
            "value": value,
            "band": strain_band(value),
            "trimp_like": 0.0,
            "rowing_trimp_like": 0.0,
            "components": [],
            "daily_activity": daily_activity,
            "explanation": (
                "No sessions logged."
                + (f" Daily activity adds {daily_activity['value']:.1f}." if daily_activity["value"] else "")
            ),
        }

    day_rpe = _note_rpe(session, day)
    max_hr = settings.get("max_hr")
    wellness = session.get(DailyWellness, day)
    resting_hr = wellness.resting_hr if wellness else None

    scores = []
    for activity in activities:
        # Per-activity RPE override (task Part C.1) beats the day's single Note.rpe — the
        # session-2 gotcha this was meant to fix (two sessions on the same day used to share
        # one RPE number).
        rpe = _overrides(activity).get("rpe", day_rpe)
        duration_minutes = (activity.duration or 0) / 60.0
        if activity.strain_trimp is not None:
            # Part E.3: per-sample Banister integration already computed in
            # catch/sync/canonical.py's resolve_canonical — never fall back to the
            # whole-session average when real samples exist.
            trimp = activity.strain_trimp
            strain = min(21.0, settings["strain_log_a"] * math.log1p(trimp)) if trimp > 0 else 0.0
            result = {
                "value": strain,
                "band": strain_band(strain) if trimp > 0 else "light",
                "components": [{"method": "trimp_samples", "trimp_like": trimp, "duration_minutes": duration_minutes}],
                "explanation": f"Per-sample Banister TRIMP over {activity.title or 'this session'}'s real HR stream -> trimp_like={trimp:.1f}.",
            }
        else:
            result = session_strain(
                duration_minutes=duration_minutes,
                avg_hr=activity.avg_hr,
                resting_hr=resting_hr,
                max_hr=max_hr,
                rpe=rpe,
                settings=settings,
            )
        scores.append({"canonical_id": activity.id, "title": activity.title, **result})

    total_trimp = sum(s["components"][0]["trimp_like"] for s in scores if s["value"] is not None)
    # Rowing-specific trimp, summed separately so Today can show rowing load apart from
    # cycling/other load (task Part B.3) without a second full strain computation.
    rowing_trimp = sum(
        s["components"][0]["trimp_like"]
        for s, a in zip(scores, activities)
        if s["value"] is not None and a.sport_family == "rowing"
    )
    daily_activity = _daily_activity_component(session, day, settings)
    if total_trimp <= 0:
        if daily_activity["value"] <= 0:
            return {
                "value": None,
                "band": "insufficient_data",
                "trimp_like": 0.0,
                "rowing_trimp_like": 0.0,
                "components": scores,
                "daily_activity": daily_activity,
                "explanation": "No session that day had enough data (HR or an RPE note) to score.",
            }
        # The workout itself couldn't be scored, but there's still real non-exercise
        # daily-activity data for the day — report that rather than a flat "insufficient
        # data" when a real (if small) number exists.
        value = daily_activity["value"]
        return {
            "value": value,
            "band": strain_band(value),
            "trimp_like": 0.0,
            "rowing_trimp_like": 0.0,
            "components": scores,
            "daily_activity": daily_activity,
            "explanation": (
                "No session that day had enough data (HR or an RPE note) to score its workout strain; "
                f"daily activity still adds {value:.1f}."
            ),
        }
    # Combine via the same log-saturation curve rather than summing 0-21 scores directly, so
    # several moderate sessions in one day don't just linearly stack toward "all out." The
    # daily-activity component is added only here, on the final 0-21 value, after the
    # log-saturation curve — never mixed into trimp_like (see daily_activity_strain).
    combined = min(21.0, settings["strain_log_a"] * math.log1p(total_trimp))
    value = min(21.0, combined + daily_activity["value"])
    return {
        "value": value,
        "band": strain_band(value),
        "trimp_like": total_trimp,
        "rowing_trimp_like": rowing_trimp,
        "components": scores,
        "daily_activity": daily_activity,
        "explanation": (
            f"{len(activities)} session(s) that day combined via log-saturation of total trimp_like="
            f"{total_trimp:.1f} -> {combined:.1f}, plus daily activity {daily_activity['value']:.1f} = {value:.1f}."
        ),
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
        select(CanonicalActivity.start).where(CanonicalActivity.start.is_not(None)).order_by(CanonicalActivity.start)
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
    path — simpler and avoids subtle staleness bugs when settings or history change.

    This is the one choke point already run after every sync (scheduler.py), backfill
    (cli.py), settings PUT, note POST, and coach-memory write (coach/tools.py) — so it's also
    where GET /api/series's per-metric cache (routes_analytics.py) gets invalidated, rather
    than duplicating "what changed history" logic at each of those call sites."""
    if not _lock.acquire(blocking=False):
        return 0
    try:
        from catch.sync.matching import run_matching

        run_matching(session)

        settings = get_settings(session)
        earliest = _earliest_date(session)
        if earliest is None:
            return 0

        lookback_days = settings["load_chronic_days"] * 2
        trimp_series: list[float] = []
        rowing_trimp_series: list[float] = []
        strain_cache: dict[date, float | None] = {}
        count = 0
        day = earliest
        today = date.today()
        while day <= today:
            strain = day_strain(session, day, settings)
            trimp_series.append(strain.get("trimp_like") or 0.0)
            rowing_trimp_series.append(strain.get("rowing_trimp_like") or 0.0)
            strain_cache[day] = strain.get("value")

            load = training_load(trimp_series[-lookback_days:], settings)
            # Rowing-only load (task Part B.3) — same EWMA math over a rowing-only trimp
            # series, so cycling/other volume never inflates the number the athlete actually
            # trains rowing against.
            rowing_load = training_load(rowing_trimp_series[-lookback_days:], settings)
            recovery = day_recovery(session, day, settings, strain_cache)

            row = session.get(DailyScore, day)
            if row is None:
                row = DailyScore(date=day)
                session.add(row)
            row.recovery_json = json.dumps(recovery)
            row.strain_json = json.dumps(strain)
            row.load_json = json.dumps(load)
            row.rowing_load_json = json.dumps(rowing_load)
            row.updated_at = datetime.now(timezone.utc)
            count += 1
            day += timedelta(days=1)

        session.commit()

        from catch.api.routes_analytics import invalidate_series_cache

        invalidate_series_cache()
        return count
    finally:
        _lock.release()
