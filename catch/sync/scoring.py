from __future__ import annotations

import json
import logging
import math
import threading
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from catch.analytics.checkin import checkin_badness, checkin_recovery_score
from catch.analytics.illness import illness_score
from catch.analytics.load import training_load
from catch.analytics.recovery import recovery_score
from catch.analytics.strain import daily_activity_strain, muscular_strain_component, session_strain, strain_band
from catch.analytics.strength import normalize_muscle_au
from catch.core.models import Activity, CanonicalActivity, CheckIn, DailyScore, DailyWellness, IllnessAck
from catch.core.settings_store import get_settings

_lock = threading.Lock()
_CONFOUND_REASONS = {"alcohol", "travel", "late_night", "vaccine"}


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


def _muscle_baseline(session: Session, day: date) -> dict[str, list[float]]:
    """Trailing 28-day daily per-muscle AU totals (one number per day it appears — missing
    days are simply absent), for catch/analytics/strength.py's normalize_muscle_au baseline.
    One query, not a 28-iteration loop — cheap enough for recompute_scores' own per-day loop
    over full history."""
    baseline_start, _ = _local_day_utc_range(day - timedelta(days=28))
    day_start, _ = _local_day_utc_range(day)
    rows = session.exec(
        select(CanonicalActivity).where(
            CanonicalActivity.start >= baseline_start,
            CanonicalActivity.start < day_start,
            CanonicalActivity.muscular_by_muscle_json.is_not(None),
        )
    ).all()
    by_day_muscle: dict[tuple, float] = {}
    for a in rows:
        if _overrides(a).get("exclude_from_totals"):
            continue
        local_day = a.start.astimezone().date()
        for muscle, au in json.loads(a.muscular_by_muscle_json).items():
            key = (local_day, muscle)
            by_day_muscle[key] = by_day_muscle.get(key, 0.0) + au
    baseline: dict[str, list[float]] = {}
    for (_, muscle), au in by_day_muscle.items():
        baseline.setdefault(muscle, []).append(au)
    return baseline


def _muscular_component(session: Session, day: date, activities: list[CanonicalActivity], settings: dict) -> dict:
    """Task Part C.1/C.2: a strength session's per-muscle AU (catch/sync/gym.py's cache) is
    normalized against its own 28-day baseline before being summed; an erg/bike session's
    small above-threshold-power AU (task Part C.1.2 — no per-muscle breakdown to normalize)
    is added in raw, since it's "default low" by construction and doesn't need baselining."""
    today_by_muscle: dict[str, float] = {}
    cardio_only_au = 0.0
    for a in activities:
        if a.muscular_by_muscle_json:
            for muscle, au in json.loads(a.muscular_by_muscle_json).items():
                today_by_muscle[muscle] = today_by_muscle.get(muscle, 0.0) + au
        elif a.muscular_load_au:
            cardio_only_au += a.muscular_load_au

    if not today_by_muscle and not cardio_only_au:
        return muscular_strain_component(0.0, settings)

    baseline = _muscle_baseline(session, day)
    total_normalized = cardio_only_au
    for muscle, au in today_by_muscle.items():
        total_normalized += normalize_muscle_au(au, baseline.get(muscle, []))
    return muscular_strain_component(total_normalized, settings)


def day_strain(session: Session, day: date, settings: dict) -> dict:
    activities = _day_activities(session, day)
    daily_activity = _daily_activity_component(session, day, settings)
    muscular = _muscular_component(session, day, activities, settings)

    if not activities:
        value = min(21.0, daily_activity["value"] + muscular["value"])
        return {
            "value": value,
            "band": strain_band(value),
            "trimp_like": 0.0,
            "rowing_trimp_like": 0.0,
            "components": [],
            "daily_activity": daily_activity,
            "cardio": {"value": 0.0, "trimp_like": 0.0},
            "muscular": muscular,
            "explanation": (
                "No sessions logged."
                + (f" Daily activity adds {daily_activity['value']:.1f}." if daily_activity["value"] else "")
                + (f" Muscular load adds {muscular['value']:.1f}." if muscular["value"] else "")
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
        scores.append({"canonical_id": activity.id, "title": activity.title, "muscular_au": activity.muscular_load_au or 0.0, **result})

    total_trimp = sum(s["components"][0]["trimp_like"] for s in scores if s["value"] is not None)
    # Rowing-specific trimp, summed separately so Today can show rowing load apart from
    # cycling/other load (task Part B.3) without a second full strain computation.
    rowing_trimp = sum(
        s["components"][0]["trimp_like"]
        for s, a in zip(scores, activities)
        if s["value"] is not None and a.sport_family == "rowing"
    )
    # Cardio and muscular each go through their own log-saturation curve independently (task
    # Part C.2/C.3 — a heavy lifting day with zero HR must still register meaningful strain,
    # which a single shared curve over a combined trimp+AU number couldn't guarantee), then
    # sum as 0-21 values; daily-activity is added last, same as before (never mixed into
    # trimp_like/muscular AU — see daily_activity_strain/muscular_strain_component).
    cardio_combined = min(21.0, settings["strain_log_a"] * math.log1p(total_trimp)) if total_trimp > 0 else 0.0
    if total_trimp <= 0 and daily_activity["value"] <= 0 and muscular["value"] <= 0:
        return {
            "value": None,
            "band": "insufficient_data",
            "trimp_like": 0.0,
            "rowing_trimp_like": 0.0,
            "components": scores,
            "daily_activity": daily_activity,
            "cardio": {"value": 0.0, "trimp_like": 0.0},
            "muscular": muscular,
            "explanation": "No session that day had enough data (HR, muscular load, or an RPE note) to score.",
        }
    value = min(21.0, min(21.0, cardio_combined + muscular["value"]) + daily_activity["value"])
    return {
        "value": value,
        "band": strain_band(value),
        "trimp_like": total_trimp,
        "rowing_trimp_like": rowing_trimp,
        "components": scores,
        "daily_activity": daily_activity,
        "cardio": {"value": cardio_combined, "trimp_like": total_trimp},
        "muscular": muscular,
        "explanation": (
            f"{len(activities)} session(s) that day: cardio trimp_like={total_trimp:.1f} -> "
            f"{cardio_combined:.1f}, muscular {muscular['value']:.1f}, daily activity "
            f"{daily_activity['value']:.1f} = {value:.1f}."
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
    checkin = session.get(CheckIn, day)
    today_checkin_score = checkin_recovery_score(checkin.soreness, checkin.stress, checkin.mood, checkin.sleep_quality) if checkin else None

    return recovery_score(
        today_ln_hrv=today_ln_hrv,
        hrv_history_ln=hrv_history,
        today_resting_hr=today_rhr,
        rhr_history=rhr_history,
        today_sleep_seconds=today_sleep,
        prior_day_strain=prior_day_strain,
        today_checkin_score=today_checkin_score,
        settings=settings,
    )


def day_illness(
    session: Session,
    day: date,
    settings: dict,
    prev_deviated_count: int,
    acr_yesterday: float | None,
    exclude_dates: set[date],
) -> dict:
    """Session 15 Part B. `exclude_dates` (days already flagged "likely", or dismissed with a
    confounding reason) are dropped from every baseline window so a run of illness — or a
    known alcohol/travel/vaccine night — never teaches the baseline that those values are
    normal (see PLAN.md's advisor note on this). `acr_yesterday` must be the *prior* day's
    training-load figure, not today's, so a workout that syncs in later today can't
    retroactively change this morning's flag."""
    window_start = day - timedelta(days=settings["illness_baseline_window_days"])
    rows = session.exec(
        select(DailyWellness).where(DailyWellness.date >= window_start, DailyWellness.date < day).order_by(DailyWellness.date)
    ).all()
    history_rows = [r for r in rows if r.date not in exclude_dates]
    rhr_history = [r.resting_hr for r in history_rows if r.resting_hr is not None]
    hrv_history = [v for v in (_ln_hrv(r) for r in history_rows) if v is not None]
    resp_history = [r.sleep_respiration_avg for r in history_rows if r.sleep_respiration_avg is not None]

    checkin_rows = session.exec(
        select(CheckIn).where(CheckIn.date >= window_start, CheckIn.date < day).order_by(CheckIn.date)
    ).all()
    checkin_history = [
        v for v in (checkin_badness(r.soreness, r.mood) for r in checkin_rows if r.date not in exclude_dates) if v is not None
    ]

    wellness = session.get(DailyWellness, day)
    checkin_today = session.get(CheckIn, day)

    return illness_score(
        today_resting_hr=wellness.resting_hr if wellness else None,
        resting_hr_history=rhr_history,
        today_ln_hrv=_ln_hrv(wellness) if wellness else None,
        hrv_history_ln=hrv_history,
        today_resp=wellness.sleep_respiration_avg if wellness else None,
        resp_history=resp_history,
        today_checkin_badness=checkin_badness(checkin_today.soreness, checkin_today.mood) if checkin_today else None,
        checkin_badness_history=checkin_history,
        prev_deviated_count=prev_deviated_count,
        acr=acr_yesterday,
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
        # Session 15 Part B: carried across iterations rather than re-querying DailyScore —
        # the loop is already chronological, so "yesterday's" state is just last iteration's
        # locals. illness_exclude_dates grows as we go so a later day's baseline never
        # includes an earlier day this same recompute already flagged "likely".
        confound_dates = {
            r for r in session.exec(select(IllnessAck.date).where(IllnessAck.dismiss_reason.in_(_CONFOUND_REASONS))).all()
        }
        illness_exclude_dates: set[date] = set(confound_dates)
        prev_acr: float | None = None
        prev_illness_count = 0
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
            illness = day_illness(session, day, settings, prev_illness_count, prev_acr, illness_exclude_dates)
            if illness["level"] == "likely":
                illness_exclude_dates.add(day)
            prev_illness_count = illness["deviated_count"]
            prev_acr = load.get("value")

            row = session.get(DailyScore, day)
            if row is None:
                row = DailyScore(date=day)
                session.add(row)
            row.recovery_json = json.dumps(recovery)
            row.strain_json = json.dumps(strain)
            row.load_json = json.dumps(load)
            row.rowing_load_json = json.dumps(rowing_load)
            row.illness_json = json.dumps(illness)
            row.updated_at = datetime.now(timezone.utc)
            count += 1

            if illness["level"] == "likely" and day not in confound_dates and session.get(IllnessAck, day) is None:
                # Insert-only (task Part B.3/B.4): a dismissal, its reason, or a backtest
                # mark must never be overwritten by a later recompute — see IllnessAck's
                # docstring in catch/core/models.py.
                session.add(IllnessAck(date=day, first_flagged_at=datetime.now(timezone.utc)))

            day += timedelta(days=1)

        session.commit()

        from catch.api.routes_analytics import invalidate_series_cache

        invalidate_series_cache()

        # Session 18 (see PLAN.md) — scoped to `today` only, deliberately outside the
        # while-loop above: that loop recomputes every historical day on every call (cheap,
        # see this function's own docstring), but re-evaluating "should we recommend X" for
        # years of history on every settings-PUT/note-POST/sync would not be. Never calls
        # back into recompute_scores (no recursion into this function's own re-entrant lock);
        # isolated in its own try/except since a bug in this newer, more heuristic subsystem
        # must never break core score recomputation, which has already committed above.
        try:
            from catch.sync.training_intelligence import generate_recommendations

            generate_recommendations(session, settings, today)
        except Exception:
            session.rollback()
            logging.getLogger("catch.scoring").exception("recommendation generation failed")

        return count
    finally:
        _lock.release()
