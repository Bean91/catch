from __future__ import annotations

"""Session 18 (see PLAN.md): the DB-facing orchestration half of training intelligence.
Governing rule, same as the pure module this hands data to (catch.analytics.
training_intelligence): reuse the existing engines rather than re-deriving them —
catch.sync.erg_test.list_tests already unifies confirmed Concept2 tests and confirmed pieces
into one tagged-with-test_type row shape, so performance trends group those rows directly
with no fuzzy re-bucketing; catch.api.routes_analytics.trends_volume already computes weekly
zone-time buckets, so distribution/consistency/insights call it directly rather than
duplicating CanonicalActivity.zones_json aggregation. All of these DB-facing imports of an
`api.routes_*` function are local (inside the function body), matching the precedent already
set by catch.sync.scoring.recompute_scores importing routes_analytics.invalidate_series_cache
the same way, to avoid a module-level import cycle between sync and api."""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from catch.analytics.erg_test import pacing_analysis
from catch.analytics.piece import points_from_splits
from catch.analytics.training_intelligence import (
    compare_equivalent_pieces,
    confidence_level,
    evaluate_data_quality_warning,
    evaluate_overload_warning,
    evaluate_recovery_suggestion,
    evaluate_training_suggestion,
    training_insights,
    training_profile,
)
from catch.core.models import CanonicalActivity, DailyScore, DailyWellness, Piece, Recommendation


def _overrides(canonical: CanonicalActivity) -> dict:
    return json.loads(canonical.overrides_json) if canonical.overrides_json else {}


def _local_day_utc_range(day: date) -> tuple[datetime, datetime]:
    local_midnight = datetime(day.year, day.month, day.day)
    return local_midnight.astimezone(timezone.utc), (local_midnight + timedelta(days=1)).astimezone(timezone.utc)


def _qualifying_activities(session: Session, start: date, end: date) -> list[CanonicalActivity]:
    """CanonicalActivity rows with a local start date in [start, end), excluding
    exclude_from_totals — the same filter every other totals/consistency reader already uses
    (catch.sync.scoring._day_activities, routes_analytics.trends_volume)."""
    start_utc, _ = _local_day_utc_range(start)
    _, end_utc = _local_day_utc_range(end - timedelta(days=1))
    rows = session.exec(select(CanonicalActivity).where(CanonicalActivity.start >= start_utc, CanonicalActivity.start < end_utc)).all()
    return [a for a in rows if not _overrides(a).get("exclude_from_totals")]


def _earliest_data_date(session: Session) -> date | None:
    wellness_min = session.exec(select(DailyWellness.date).order_by(DailyWellness.date)).first()
    activity_min = session.exec(
        select(CanonicalActivity.start).where(CanonicalActivity.start.is_not(None)).order_by(CanonicalActivity.start)
    ).first()
    candidates = [d for d in (wellness_min, activity_min.astimezone().date() if activity_min else None) if d]
    return min(candidates) if candidates else None


def _history_days(session: Session, today: date) -> int:
    earliest = _earliest_data_date(session)
    return (today - earliest).days if earliest else 0


# --- Performance trends ------------------------------------------------------------------------


def gather_performance_trends(session: Session, settings: dict, piece_type: str | None = None) -> dict:
    from catch.sync.erg_test import list_tests

    cutoff = date.today() - timedelta(days=settings["training_intelligence"]["piece_trend_lookback_days"])
    rows = [r for r in list_tests(session, piece_type) if r.get("date") and date.fromisoformat(r["date"]) >= cutoff]
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("test_type"):
            by_type[r["test_type"]].append(r)
    buckets = [compare_equivalent_pieces(t, group, settings) for t, group in by_type.items()]
    buckets.sort(key=lambda b: b["bucket_label"])
    return {"buckets": buckets}


# --- Training distribution ---------------------------------------------------------------------


def gather_training_distribution(session: Session, settings: dict, weeks: int = 12) -> dict:
    from catch.api.routes_analytics import trends_volume

    vol_weeks = trends_volume(weeks=weeks, db=session)
    if not vol_weeks:
        return {"weeks": []}
    range_start, range_end = vol_weeks[0]["week_start"], vol_weeks[-1]["week_start"] + timedelta(days=7)
    activities = _qualifying_activities(session, range_start, range_end)

    strength_minutes: dict[date, float] = {w["week_start"]: 0.0 for w in vol_weeks}
    for a in activities:
        if a.sport_family != "strength" or not a.duration:
            continue
        local_date = a.start.astimezone().date()
        bucket_week = local_date - timedelta(days=local_date.weekday())
        if bucket_week in strength_minutes:
            strength_minutes[bucket_week] += a.duration / 60.0

    weeks_out = [{**w, "strength_minutes": strength_minutes.get(w["week_start"], 0.0)} for w in vol_weeks]
    return {"weeks": weeks_out}


# --- Training consistency ----------------------------------------------------------------------


def _clamped_window(session: Session, today: date, weeks: int) -> tuple[date, date]:
    """The nominal `weeks`-wide window, clamped on both ends to what could actually have
    happened: never past today (counting not-yet-elapsed days of the current week as "rest
    days"/part of a gap is simply wrong), and never before the account's own earliest data
    (a fresh install's pre-history isn't a training gap, it's the absence of the app itself —
    see the advisor-review note in PLAN.md's session 18 entry)."""
    this_week_start = today - timedelta(days=today.weekday())
    nominal_start = this_week_start - timedelta(weeks=weeks - 1)
    earliest = _earliest_data_date(session)
    range_start = max(nominal_start, earliest) if earliest else nominal_start
    range_end = min(this_week_start + timedelta(days=7), today + timedelta(days=1))
    return range_start, max(range_end, range_start)


def gather_training_consistency(session: Session, settings: dict, weeks: int | None = None) -> dict:
    ti = settings["training_intelligence"]
    weeks = weeks or ti["consistency_lookback_weeks"]
    today = date.today()
    range_start, range_end = _clamped_window(session, today, weeks)
    activities = _qualifying_activities(session, range_start, range_end)
    elapsed_days = max(0, (range_end - range_start).days)
    elapsed_weeks = elapsed_days / 7.0

    by_week: dict[date, list[CanonicalActivity]] = defaultdict(list)
    for a in activities:
        local_date = a.start.astimezone().date()
        bucket_week = local_date - timedelta(days=local_date.weekday())
        by_week[bucket_week].append(a)

    total_sessions = len(activities)
    strength_sessions = sum(1 for a in activities if a.sport_family == "strength")
    active_days = {a.start.astimezone().date() for a in activities}
    rest_days = elapsed_days - len(active_days)

    concentrated_block = False
    for acts in by_week.values():
        # Fewer than 3 sessions in a week trivially passes a "top-2-days share" check (with 1
        # or 2 sessions, the top two days ARE the whole week) — gated so this only flags a
        # real concentration pattern, not an artifact of a light week.
        if len(acts) < 3:
            continue
        week_total = sum((a.duration or 0.0) for a in acts)
        if week_total <= 0:
            continue
        by_day: dict[date, float] = defaultdict(float)
        for a in acts:
            by_day[a.start.astimezone().date()] += a.duration or 0.0
        top_two = sorted(by_day.values(), reverse=True)[:2]
        if sum(top_two) / week_total >= ti["concentrated_block_max_day_share"]:
            concentrated_block = True
            break

    target_sessions = round(ti["target_sessions_per_week"] * elapsed_weeks)
    sessions_pct = (total_sessions / target_sessions) if target_sessions else None

    total_minutes = sum((a.duration or 0.0) for a in activities) / 60.0
    minutes_target = round(ti["target_minutes_per_week"] * elapsed_weeks)
    minutes_pct = (total_minutes / minutes_target) if minutes_target else None

    # The more conservative of the two — hitting the session-count target with unusually
    # short sessions (or vice versa) shouldn't read as full consistency on either axis alone.
    candidates = [p for p in (sessions_pct, minutes_pct) if p is not None]
    pct_of_target = min(candidates) if candidates else None

    if total_sessions == 0 or elapsed_weeks < 1:
        band, explanation = "insufficient_data", "Not enough elapsed history in this window yet."
    elif pct_of_target is not None and pct_of_target >= 0.9:
        band, explanation = "on_target", f"{total_sessions} sessions ({round(total_minutes)} min) over the last {elapsed_days} day(s), at or above the weekly target."
    elif pct_of_target is not None and pct_of_target >= 0.6:
        band, explanation = "below_target", f"{total_sessions} sessions ({round(total_minutes)} min) over the last {elapsed_days} day(s), below the weekly target."
    else:
        band, explanation = "well_below_target", f"Only {total_sessions} sessions ({round(total_minutes)} min) over the last {elapsed_days} day(s), well below the weekly target."

    from catch.api.routes_analytics import trends_volume

    vol_weeks = trends_volume(weeks=weeks, db=session)
    zone_totals: dict[str, float] = defaultdict(float)
    for w in vol_weeks:
        for z, secs in w["zones"].items():
            zone_totals[z] += secs
    total_zone_secs = sum(zone_totals.values())
    distribution_pct = {z: (secs / total_zone_secs if total_zone_secs else 0.0) for z, secs in zone_totals.items()}

    return {
        "sessions_completed": total_sessions,
        "sessions_target": target_sessions,
        "minutes_completed": round(total_minutes),
        "minutes_target": minutes_target,
        "pct_of_target": pct_of_target,
        "rest_days": max(0, rest_days),
        "concentrated_block": concentrated_block,
        "distribution_pct": distribution_pct,
        "strength_sessions": strength_sessions,
        "band": band,
        "explanation": explanation,
        "confidence": confidence_level(_history_days(session, today), total_sessions, settings),
    }


# --- Insights ------------------------------------------------------------------------------------


def _weekday_counts(activities: list[CanonicalActivity]) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for a in activities:
        counts[a.start.astimezone().weekday()] += 1
    return dict(counts)


def _max_gap_days(activities: list[CanonicalActivity], range_start: date, range_end: date) -> int | None:
    days = sorted({a.start.astimezone().date() for a in activities})
    points = [range_start, *days, range_end]
    gaps = [(points[i + 1] - points[i]).days for i in range(len(points) - 1)]
    return max(gaps) if gaps else None


def _fast_start_flags(session: Session, limit: int = 10) -> list[bool]:
    """Bounded to the most recent confirmed pieces (any type) that carry inline splits_json —
    zero extra queries beyond this one, unlike re-fetching a confirmed test's real Concept2
    stroke data, which this deliberately skips to keep this cheap enough to run from
    generate_recommendations' context assembly."""
    rows = session.exec(select(Piece).order_by(Piece.created_at.desc()).limit(limit)).all()
    flags = []
    for p in rows:
        if not p.splits_json or not p.distance_m:
            continue
        points = points_from_splits(json.loads(p.splits_json))
        if len(points) < 3:
            continue
        analysis = pacing_analysis(points, p.distance_m)
        start_s, sprint_s = analysis["segments"]["start"], analysis["segments"]["sprint"]
        if start_s and sprint_s:
            flags.append((sprint_s - start_s) / start_s > 0.03)
    return flags


def _recovery_after_high_strain(session: Session, start: date, end: date) -> tuple[list[dict], float | None]:
    rows = session.exec(select(DailyScore).where(DailyScore.date >= start, DailyScore.date < end).order_by(DailyScore.date)).all()
    by_date = {r.date: r for r in rows}
    pairs, recoveries = [], []
    for r in rows:
        if r.recovery_json:
            rec = json.loads(r.recovery_json).get("value")
            if rec is not None:
                recoveries.append(rec)
        if not r.strain_json:
            continue
        strain_value = json.loads(r.strain_json).get("value")
        if strain_value is None or strain_value < 14:  # strain.py's strain_band "high"/"all_out" boundary
            continue
        next_row = by_date.get(r.date + timedelta(days=1))
        after = json.loads(next_row.recovery_json).get("value") if next_row and next_row.recovery_json else None
        pairs.append({"date": r.date.isoformat(), "after": after})
    baseline_avg = (sum(recoveries) / len(recoveries)) if recoveries else None
    return pairs, baseline_avg


def gather_training_insights(session: Session, settings: dict) -> list[dict]:
    ti = settings["training_intelligence"]
    today = date.today()
    weeks = ti["consistency_lookback_weeks"]
    range_start, range_end = _clamped_window(session, today, weeks)
    activities = _qualifying_activities(session, range_start, range_end)

    from catch.api.routes_analytics import trends_volume

    vol_weeks = trends_volume(weeks=weeks, db=session)
    recent_weeks = vol_weeks[-2:]
    baseline_weeks = vol_weeks[:-2] or vol_weeks

    def _pct(weeks_subset: list[dict]) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for w in weeks_subset:
            for z, secs in w["zones"].items():
                totals[z] += secs
        grand = sum(totals.values())
        return {z: (secs / grand if grand else 0.0) for z, secs in totals.items()}

    pairs, baseline_avg = _recovery_after_high_strain(session, range_start, range_end)
    context = {
        "weekday_counts": _weekday_counts(activities),
        "recovery_after_high_strain": pairs,
        "recovery_baseline_avg": baseline_avg,
        "fast_start_flags": _fast_start_flags(session),
        "zone_pct_recent": _pct(recent_weeks),
        "zone_pct_baseline": _pct(baseline_weeks),
        "max_gap_days": _max_gap_days(activities, range_start, range_end),
    }
    return training_insights(context, settings)


# --- Training profile ---------------------------------------------------------------------------


def _nutrition_context(session: Session, today: date) -> dict:
    """"When available" (task's own phrase) — never treated as zero when the athlete simply
    hasn't logged anything, only reported as "not logged"."""
    from catch.sync import nutrition

    summary = nutrition.week_summary(session, today - timedelta(days=6), today)
    logged_days = summary["under_fuelling"]["logged_days"]
    if logged_days == 0:
        return {"logged": False}
    return {"logged": True, "logged_days": logged_days, "under_fuelling": summary["under_fuelling"]["flag"]}


def _daily_activity_context(session: Session, today: date) -> dict:
    wellness = session.get(DailyWellness, today)
    if wellness is None or wellness.steps is None:
        return {"logged": False}
    return {"logged": True, "steps": wellness.steps, "active_kcal": wellness.active_kcal}


def _recent_note(session: Session, today: date) -> str | None:
    from catch.core.models import Note

    rows = session.exec(
        select(Note).where(Note.date >= today - timedelta(days=7)).order_by(Note.id.desc())
    ).all()
    return rows[0].text if rows else None


def gather_training_profile(session: Session, settings: dict) -> dict:
    today = date.today()
    score_row = session.get(DailyScore, today)
    load = json.loads(score_row.load_json) if score_row and score_row.load_json else {"value": None, "band": "insufficient_data"}
    recovery = json.loads(score_row.recovery_json) if score_row and score_row.recovery_json else {"value": None, "band": "calibrating"}
    illness = json.loads(score_row.illness_json) if score_row and score_row.illness_json else {"level": "none", "explanation": ""}

    from catch.sync.erg_test import next_relevant_event

    event = next_relevant_event(session, today)
    next_event = None
    if event is not None:
        next_event = {"name": event.name, "date": event.date.isoformat(), "days_to_go": (event.date - today).days, "priority": event.priority}

    trends = gather_performance_trends(session, settings)
    consistency = gather_training_consistency(session, settings)

    components = {
        "load": load,
        "recovery": recovery,
        "illness": illness,
        "next_event": next_event,
        "history_days": _history_days(session, today),
        "trend_buckets": trends["buckets"],
        "consistency_summary": {"band": consistency["band"], "explanation": consistency["explanation"]},
        # Context only, not yet factored into phase/strengths/confidence — see the "Not yet
        # done" note in PLAN.md's session 18 entry.
        "nutrition": _nutrition_context(session, today),
        "daily_activity": _daily_activity_context(session, today),
        "recent_note": _recent_note(session, today),
    }
    return training_profile(components, settings)


# --- Recommendations -----------------------------------------------------------------------------


def is_active(row: Recommendation, today: date | None = None) -> bool:
    today = today or date.today()
    return not row.dismissed and row.last_confirmed_on >= today - timedelta(days=1)


def recommendation_dict(row: Recommendation) -> dict:
    return {
        "id": row.id,
        "date": row.date,
        "type": row.type,
        "confidence": row.confidence,
        "title": row.title,
        "body": row.body,
        "evidence": json.loads(row.evidence_json) if row.evidence_json else [],
        "last_confirmed_on": row.last_confirmed_on,
        "dismissed": row.dismissed,
        "saved": row.saved,
        "rating": row.rating,
        "active": is_active(row),
    }


_MAX_RECOMMENDATIONS = 50


def list_recommendations(session: Session, status: str = "active", type_: str | None = None) -> list[dict]:
    """`status == "active"` filters at the SQL level (dismissed=False and last_confirmed_on
    within the 1-day grace window) rather than loading every row this table has ever held and
    filtering in Python — this is read on every chat turn via memory_block, so an
    ever-growing table must never make that read scale with the table's full history. Always
    capped at `_MAX_RECOMMENDATIONS`, same `_downsample`/`_MAX_ROWS`-style row-cap convention
    every other range tool in this app already follows (coach/tools.py)."""
    stmt = select(Recommendation)
    if type_:
        stmt = stmt.where(Recommendation.type == type_)
    if status == "dismissed":
        stmt = stmt.where(Recommendation.dismissed.is_(True))
    elif status == "active":
        stmt = stmt.where(Recommendation.dismissed.is_(False), Recommendation.last_confirmed_on >= date.today() - timedelta(days=1))
    rows = session.exec(stmt.order_by(Recommendation.created_at.desc()).limit(_MAX_RECOMMENDATIONS)).all()
    return [recommendation_dict(r) for r in rows]


def _missing_hr_pct(session: Session, lookback_n: int) -> tuple[float | None, int]:
    """Strength sessions are excluded — they structurally don't carry the same cardio HR
    signal (a lifting session often has no meaningful avg_hr even when everything else about
    the recording is fine), so counting them here would falsely inflate "missing HR" for any
    athlete who lifts regularly."""
    rows = session.exec(
        select(CanonicalActivity)
        .where(CanonicalActivity.start.is_not(None), CanonicalActivity.sport_family != "strength")
        .order_by(CanonicalActivity.start.desc())
        .limit(lookback_n)
    ).all()
    rows = [a for a in rows if not _overrides(a).get("exclude_from_totals")]
    if not rows:
        return None, 0
    missing = sum(1 for a in rows if a.avg_hr is None)
    return missing / len(rows), len(rows)


def _sessions_this_week(session: Session, today: date) -> int:
    this_week_start = today - timedelta(days=today.weekday())
    return len(_qualifying_activities(session, this_week_start, today + timedelta(days=1)))


def _acr_series(session: Session, today: date, n: int) -> list[float | None]:
    rows = session.exec(
        select(DailyScore).where(DailyScore.date > today - timedelta(days=n), DailyScore.date <= today).order_by(DailyScore.date)
    ).all()
    by_date = {r.date: r for r in rows}
    out, day = [], today - timedelta(days=n - 1)
    while day <= today:
        row = by_date.get(day)
        out.append(json.loads(row.load_json).get("value") if row and row.load_json else None)
        day += timedelta(days=1)
    return out


def _upsert_recommendation(session: Session, type_name: str, result: dict, today: date, settings: dict) -> Recommendation | None:
    """Dedup/cooldown: a `rule_key` created within its cooldown window is re-confirmed in
    place (last_confirmed_on bumped, no duplicate row) rather than inserted again; dismissal
    does not reset the cooldown — a dismissed row within the window still blocks a new one.
    Once the cooldown has fully elapsed, a fresh row is created even if the previous one of
    this rule_key was dismissed — a recurring issue is fair to re-surface after enough time."""
    ti = settings["training_intelligence"]
    cooldown_days = ti["recovery_suggestion_cooldown_days"] if type_name == "recovery_suggestion" else ti["recommendation_cooldown_days"]
    existing = session.exec(
        select(Recommendation).where(Recommendation.rule_key == result["rule_key"]).order_by(Recommendation.created_at.desc())
    ).first()
    # .astimezone() (not a bare .date()) — created_at is UTC-aware, today is a local-calendar
    # date, and comparing a raw UTC date against it is the exact day-boundary bug class
    # scoring.py's own _local_day_utc_range docstring already warns about.
    if existing is not None and existing.created_at.astimezone().date() >= today - timedelta(days=cooldown_days):
        existing.last_confirmed_on = today
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
        return None
    row = Recommendation(
        date=today,
        type=type_name,
        rule_key=result["rule_key"],
        confidence=result["confidence"],
        title=result["title"],
        body=result["body"],
        evidence_json=json.dumps(result.get("evidence") or []),
        last_confirmed_on=today,
    )
    session.add(row)
    return row


def generate_recommendations(session: Session, settings: dict, today: date) -> list[Recommendation]:
    """Called once from catch.sync.scoring.recompute_scores, after its own commit, scoped to
    `today` only. Deliberately cheap — no 365-day performance-trend scan (that stays in
    gather_performance_trends, only run when that tool/route is hit): just today's cached
    DailyScore, a bounded recent-activity count for the data-quality check, today's niggle
    streak, this week's session count, and the next event."""
    ti = settings["training_intelligence"]
    score_row = session.get(DailyScore, today)
    load = json.loads(score_row.load_json) if score_row and score_row.load_json else {"value": None, "band": "insufficient_data"}
    recovery = json.loads(score_row.recovery_json) if score_row and score_row.recovery_json else {"value": None, "band": "calibrating"}
    illness = json.loads(score_row.illness_json) if score_row and score_row.illness_json else {"level": "none", "explanation": ""}

    from catch.api.routes_checkins import niggle_streak_days
    from catch.sync.erg_test import next_relevant_event

    event = next_relevant_event(session, today)
    next_event = None
    if event is not None:
        next_event = {"name": event.name, "date": event.date.isoformat(), "days_to_go": (event.date - today).days}

    missing_hr_pct, lookback_n = _missing_hr_pct(session, ti["data_quality_lookback_sessions"])

    context = {
        "load": load,
        "recovery": recovery,
        "illness": illness,
        "next_event": next_event,
        "history_days": _history_days(session, today),
        "niggle_streak_days": niggle_streak_days(session, today),
        "sessions_this_week": _sessions_this_week(session, today),
        "acr_recent": _acr_series(session, today, ti["overload_min_consecutive_days"]),
        "missing_hr_pct": missing_hr_pct,
        "missing_hr_lookback_n": lookback_n,
    }

    evaluators = (
        ("data_quality_warning", evaluate_data_quality_warning),
        ("overload_warning", evaluate_overload_warning),
        ("recovery_suggestion", evaluate_recovery_suggestion),
        ("training_suggestion", evaluate_training_suggestion),
    )
    # A training suggestion is never evaluated in the same run as a fired recovery/overload
    # warning — both are more specific, more urgent signals, and a "room for another session"
    # suggestion alongside either would be a direct contradiction (the exact bug an advisor
    # review caught live: recovery at the yellow/red boundary could fire both at once).
    fired_this_run: set[str] = set()
    created = []
    for type_name, fn in evaluators:
        if type_name == "training_suggestion" and fired_this_run & {"recovery_suggestion", "overload_warning"}:
            continue
        result = fn(context, settings)
        if result is None:
            continue
        fired_this_run.add(type_name)
        row = _upsert_recommendation(session, type_name, result, today, settings)
        if row is not None:
            created.append(row)
    session.commit()
    return created
