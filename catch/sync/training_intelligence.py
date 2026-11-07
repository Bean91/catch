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


def _history_days(session: Session, today: date) -> int:
    wellness_min = session.exec(select(DailyWellness.date).order_by(DailyWellness.date)).first()
    activity_min = session.exec(
        select(CanonicalActivity.start).where(CanonicalActivity.start.is_not(None)).order_by(CanonicalActivity.start)
    ).first()
    candidates = [d for d in (wellness_min, activity_min.astimezone().date() if activity_min else None) if d]
    return (today - min(candidates)).days if candidates else 0


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


def gather_training_consistency(session: Session, settings: dict, weeks: int | None = None) -> dict:
    ti = settings["training_intelligence"]
    weeks = weeks or ti["consistency_lookback_weeks"]
    today = date.today()
    this_week_start = today - timedelta(days=today.weekday())
    range_start = this_week_start - timedelta(weeks=weeks - 1)
    range_end = this_week_start + timedelta(days=7)
    activities = _qualifying_activities(session, range_start, range_end)

    by_week: dict[date, list[CanonicalActivity]] = defaultdict(list)
    for a in activities:
        local_date = a.start.astimezone().date()
        bucket_week = local_date - timedelta(days=local_date.weekday())
        by_week[bucket_week].append(a)

    total_sessions = len(activities)
    strength_sessions = sum(1 for a in activities if a.sport_family == "strength")
    active_days = {a.start.astimezone().date() for a in activities}
    total_days = (range_end - range_start).days
    rest_days = total_days - len(active_days)

    concentrated_block = False
    for acts in by_week.values():
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

    target_sessions = ti["target_sessions_per_week"] * weeks
    pct_of_target = (total_sessions / target_sessions) if target_sessions else None

    if total_sessions == 0:
        band, explanation = "insufficient_data", "No sessions logged in this window yet."
    elif pct_of_target is not None and pct_of_target >= 0.9:
        band, explanation = "on_target", f"{total_sessions} sessions over {weeks} week(s), at or above the weekly target."
    elif pct_of_target is not None and pct_of_target >= 0.6:
        band, explanation = "below_target", f"{total_sessions} sessions over {weeks} week(s), below the weekly target."
    else:
        band, explanation = "well_below_target", f"Only {total_sessions} sessions over {weeks} week(s), well below the weekly target."

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
        "pct_of_target": pct_of_target,
        "rest_days": rest_days,
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
    this_week_start = today - timedelta(days=today.weekday())
    range_start = this_week_start - timedelta(weeks=weeks - 1)
    range_end = this_week_start + timedelta(days=7)
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


def list_recommendations(session: Session, status: str = "active", type_: str | None = None) -> list[dict]:
    stmt = select(Recommendation)
    if type_:
        stmt = stmt.where(Recommendation.type == type_)
    rows = session.exec(stmt.order_by(Recommendation.created_at.desc())).all()
    if status == "dismissed":
        rows = [r for r in rows if r.dismissed]
    elif status == "active":
        rows = [r for r in rows if is_active(r)]
    return [recommendation_dict(r) for r in rows]


def _missing_hr_pct(session: Session, lookback_n: int) -> tuple[float | None, int]:
    rows = session.exec(
        select(CanonicalActivity).where(CanonicalActivity.start.is_not(None)).order_by(CanonicalActivity.start.desc()).limit(lookback_n)
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
    if existing is not None and existing.created_at.date() >= today - timedelta(days=cooldown_days):
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
    created = []
    for type_name, fn in evaluators:
        result = fn(context, settings)
        if result is None:
            continue
        row = _upsert_recommendation(session, type_name, result, today, settings)
        if row is not None:
            created.append(row)
    session.commit()
    return created
