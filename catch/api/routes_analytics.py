from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlmodel import Session, select

from catch.analytics.body import smooth_weight
from catch.analytics.erg_math import w_per_kg
from catch.analytics.predict import predict_2k
from catch.analytics.strain import hr_sample_durations, time_in_zone
from catch.analytics.technique import erg_technique, interval_summary
from catch.analytics.zones import ZONE_ORDER, zone_for_hr
from catch.api.deps import as_utc, get_db, require_auth
from catch.core.models import Activity, BodyComp, DailyScore, DailyWellness, Stroke
from catch.core.settings_store import get_settings, update_settings

router = APIRouter(dependencies=[Depends(require_auth)])

# Interval/piece workouts mix work and rest into Activity.duration while distance stays
# work-only (see docs/concept2-endpoints.md); Paul's law needs a clean distance/time pair, so
# 2k prediction only draws from continuous, uninterrupted efforts.
_CONTINUOUS_WORKOUT_TYPES = {None, "unknown", "JustRow", "FixedDistanceSplits", "FixedTimeSplits"}

_WELLNESS_METRICS = {
    "resting_hr",
    "hrv_rmssd",
    "sleep_seconds",
    "sleep_score",
    "stress",
    "body_battery",
    "spo2",
    "respiration",
}
_SCORE_METRICS = {"recovery": "recovery_json", "strain": "strain_json", "load_acr": "load_json"}


def _score_dict(raw: str | None) -> dict | None:
    return json.loads(raw) if raw else None


def _recommendation(recovery: dict | None, load: dict | None) -> str:
    if not recovery or recovery.get("band") is None:
        return "Not enough data yet to make a recommendation — keep syncing."
    band = recovery["band"]
    if band == "calibrating":
        return "Still calibrating your recovery baseline (need 7+ nights of HRV) — no number yet."
    if band == "red":
        return "Recovery is low — consider an easy day or full rest."
    if band == "yellow":
        return "Recovery is moderate — stick to UT2/UT1 work today."
    if (load or {}).get("band") == "high_risk":
        return "Recovery is green, but your acute:chronic ratio is in the high-risk band — add load cautiously."
    return "Recovery is green — you're clear for a harder session if it's on the plan."


def _component(components: list[dict] | None, metric: str) -> dict | None:
    for c in components or []:
        if c.get("metric") == metric:
            return c
    return None


def _sparkline(db: Session, field: str, days: int, through: date) -> list[dict]:
    since = through - timedelta(days=days - 1)
    stmt = select(DailyWellness).where(DailyWellness.date >= since, DailyWellness.date <= through)
    rows = db.exec(stmt.order_by(DailyWellness.date)).all()
    return [{"date": r.date, "value": getattr(r, field)} for r in rows]


def _baseline_band(component: dict | None, log_space: bool) -> dict | None:
    """Reuses the baseline/spread already computed by recovery_score rather than
    re-deriving the 7d-mean/60d-pstdev in the frontend. HRV's baseline/spread are in
    ln-space (recovery.py comment: lognormal), so the ±1-spread band is exponentiated
    back to ms for display; resting HR's are already in raw bpm."""
    if component is None:
        return None
    baseline = component.get("baseline_7d_ln") if log_space else component.get("baseline_7d")
    spread = component.get("spread_60d")
    if baseline is None:
        return None
    if spread is None:
        low = high = baseline
    else:
        low, high = baseline - spread, baseline + spread
    if log_space:
        baseline, low, high = math.exp(baseline), math.exp(low), math.exp(high)
    return {"baseline": baseline, "low": low, "high": high}


def _latest_erg(db: Session) -> dict | None:
    stmt = select(Activity).where(Activity.source == "concept2").order_by(Activity.start.desc())
    row = db.exec(stmt).first()
    if row is None:
        return None
    weight_kg = _nearest_weight_kg(db, row.start)
    data = row.model_dump(exclude={"raw_json", "intervals_json"})
    data["weight_kg"] = weight_kg
    data["w_per_kg"] = w_per_kg(row.avg_power, weight_kg)
    return data


@router.get("/api/today")
def today(db: Session = Depends(get_db)):
    today_date = date.today()
    score_row = db.get(DailyScore, today_date)
    wellness = db.get(DailyWellness, today_date)
    recovery = _score_dict(score_row.recovery_json) if score_row else None
    strain = _score_dict(score_row.strain_json) if score_row else None
    load = _score_dict(score_row.load_json) if score_row else None
    settings = get_settings(db)

    components = recovery.get("components") if recovery else None
    band_for_targets = (recovery or {}).get("band") or "calibrating"
    strain_target = settings["strain_targets"].get(band_for_targets, settings["strain_targets"]["calibrating"])

    return {
        "date": today_date,
        "recovery": recovery,
        "sleep_last_night": (
            {
                "seconds": wellness.sleep_seconds,
                "score": wellness.sleep_score,
                "need_seconds": settings["sleep_need_seconds"],
                "deep_seconds": wellness.deep_sleep_seconds,
                "light_seconds": wellness.light_sleep_seconds,
                "rem_seconds": wellness.rem_sleep_seconds,
                "awake_seconds": wellness.awake_sleep_seconds,
            }
            if wellness
            else None
        ),
        "strain_today": strain,
        "strain_target_range": strain_target,
        "load": load,
        "hrv": {
            "today": wellness.hrv_rmssd if wellness else None,
            "sparkline_14d": _sparkline(db, "hrv_rmssd", 14, today_date),
            "baseline_band": _baseline_band(_component(components, "hrv"), log_space=True),
        },
        "resting_hr": {
            "today": wellness.resting_hr if wellness else None,
            "sparkline_14d": _sparkline(db, "resting_hr", 14, today_date),
            "baseline_band": _baseline_band(_component(components, "resting_hr"), log_space=False),
        },
        "latest_erg": _latest_erg(db),
        "predicted_2k": _predict_2k(db, settings),
        "recommendation": _recommendation(recovery, load),
    }


@router.get("/api/trends")
def trends(
    metric: str = Query(...),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    db: Session = Depends(get_db),
):
    if metric in _WELLNESS_METRICS:
        stmt = select(DailyWellness)
        if from_:
            stmt = stmt.where(DailyWellness.date >= from_)
        if to:
            stmt = stmt.where(DailyWellness.date <= to)
        rows = db.exec(stmt.order_by(DailyWellness.date)).all()
        return [{"date": r.date, "value": getattr(r, metric)} for r in rows]

    if metric in _SCORE_METRICS:
        field = _SCORE_METRICS[metric]
        stmt = select(DailyScore)
        if from_:
            stmt = stmt.where(DailyScore.date >= from_)
        if to:
            stmt = stmt.where(DailyScore.date <= to)
        rows = db.exec(stmt.order_by(DailyScore.date)).all()
        out = []
        for r in rows:
            d = _score_dict(getattr(r, field)) or {}
            point = {"date": r.date, "value": d.get("value")}
            if metric == "load_acr" and d.get("components"):
                # Trends' load/form view needs the acute/chronic/form series, not just the
                # ratio — these already exist per-day on the cached component, no recompute.
                point.update({k: v for k, v in d["components"][0].items()})
            out.append(point)
        return out

    if metric == "weight":
        return _weight_trend(db, from_, to)
    if metric == "w_per_kg":
        return _w_per_kg_trend(db, from_, to)
    if metric == "predicted_2k":
        return _predicted_2k_trend(db, from_, to)

    allowed = sorted(_WELLNESS_METRICS | set(_SCORE_METRICS) | {"weight", "w_per_kg", "predicted_2k"})
    raise HTTPException(status_code=400, detail=f"Unknown metric '{metric}'. Allowed: {allowed}")


def _date_bounds(from_: date | None, to: date | None) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(from_, datetime.min.time(), tzinfo=timezone.utc) if from_ else None
    end = datetime.combine(to, datetime.max.time(), tzinfo=timezone.utc) if to else None
    return start, end


def _weight_trend(db: Session, from_: date | None, to: date | None) -> list[dict]:
    # Smoothed over *all* history, not just the requested range — otherwise the smoothed
    # line at the start of a narrow range (e.g. "4w") would have no trailing context and
    # read as noisier than it should.
    start, end = _date_bounds(from_, to)
    all_rows = db.exec(select(BodyComp).where(BodyComp.weight_kg.is_not(None)).order_by(BodyComp.ts)).all()
    smoothed_by_day = dict(smooth_weight([(r.ts.date(), r.weight_kg) for r in all_rows]))
    out = []
    for r in all_rows:
        if start and r.ts < start:
            continue
        if end and r.ts > end:
            continue
        out.append({"date": r.ts.date(), "value": r.weight_kg, "smoothed": smoothed_by_day.get(r.ts.date())})
    return out


def _w_per_kg_trend(db: Session, from_: date | None, to: date | None) -> list[dict]:
    start, end = _date_bounds(from_, to)
    stmt = select(Activity).where(Activity.source == "concept2", Activity.avg_power.is_not(None))
    if start:
        stmt = stmt.where(Activity.start >= start)
    if end:
        stmt = stmt.where(Activity.start <= end)
    rows = db.exec(stmt.order_by(Activity.start)).all()
    out = []
    for a in rows:
        weight_kg = _nearest_weight_kg(db, a.start)
        value = w_per_kg(a.avg_power, weight_kg)
        if value is not None and a.start is not None:
            out.append({"date": a.start.date(), "value": value})
    return out


def _predicted_2k_trend(db: Session, from_: date | None, to: date | None) -> list[dict]:
    """One point per qualifying effort: that single piece's own Paul's-law extrapolation to
    2000m (same formula `/api/predict/2k` uses, but per-piece rather than averaged across
    several recent pieces) — a trend of "what would today's piece alone predict," distinct
    from the Today screen's multi-piece ensemble estimate."""
    start, end = _date_bounds(from_, to)
    stmt = select(Activity).where(
        Activity.source == "concept2",
        Activity.type == "rower",
        Activity.distance.is_not(None),
        Activity.duration.is_not(None),
    )
    if start:
        stmt = stmt.where(Activity.start >= start)
    if end:
        stmt = stmt.where(Activity.start <= end)
    rows = db.exec(stmt.order_by(Activity.start)).all()
    out = []
    for a in rows:
        if a.workout_type not in _CONTINUOUS_WORKOUT_TYPES or not a.distance or a.distance < 1000 or a.start is None:
            continue
        pace = (a.duration / a.distance) * 500.0
        result = predict_2k([{"distance_m": a.distance, "pace_s_per_500": pace, "label": a.start.date().isoformat()}])
        if result["value"] is not None:
            out.append({"date": a.start.date(), "value": result["predicted_time_s"]})
    return out


def _nearest_weight_kg(db: Session, when: datetime | None) -> float | None:
    """Nearest body_comp (Withings) weight in time to `when` — whichever of the closest row
    at-or-before and the closest row at-or-after is nearer. None if there's no weight data
    yet (Withings OAuth isn't completed as of session 1/2)."""
    if when is None:
        return None
    before = db.exec(
        select(BodyComp).where(BodyComp.ts <= when, BodyComp.weight_kg.is_not(None)).order_by(BodyComp.ts.desc())
    ).first()
    after = db.exec(
        select(BodyComp).where(BodyComp.ts >= when, BodyComp.weight_kg.is_not(None)).order_by(BodyComp.ts.asc())
    ).first()
    candidates = [c for c in (before, after) if c is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs((c.ts - when).total_seconds())).weight_kg


@router.get("/api/erg/results")
def erg_results(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    db: Session = Depends(get_db),
):
    from_, to = as_utc(from_), as_utc(to)
    stmt = select(Activity).where(Activity.source == "concept2")
    if from_:
        stmt = stmt.where(Activity.start >= from_)
    if to:
        stmt = stmt.where(Activity.start <= to)
    rows = db.exec(stmt.order_by(Activity.start.desc())).all()

    out = []
    for a in rows:
        weight_kg = _nearest_weight_kg(db, a.start)
        out.append({**a.model_dump(), "weight_kg": weight_kg, "w_per_kg": w_per_kg(a.avg_power, weight_kg)})
    return out


@router.get("/api/erg/{activity_id}/strokes")
def erg_strokes(activity_id: int, db: Session = Depends(get_db)):
    activity = db.get(Activity, activity_id)
    if activity is None or activity.source != "concept2":
        raise HTTPException(status_code=404, detail="Concept2 result not found")
    strokes = db.exec(select(Stroke).where(Stroke.activity_id == activity_id).order_by(Stroke.seq)).all()

    by_interval: dict[int, list[Stroke]] = {}
    for s in strokes:
        by_interval.setdefault(s.interval_index or 0, []).append(s)

    settings = get_settings(db)
    max_hr = settings.get("max_hr")
    technique_by_interval = {}
    time_in_zone_by_interval = {}
    interval_summaries: dict[int, dict] = {}
    for idx, group in sorted(by_interval.items()):
        pieces = [
            {"t": s.t, "distance": s.distance, "watts": s.watts, "stroke_rate": s.stroke_rate, "pace_500m": s.pace_500m, "hr": s.hr}
            for s in group
        ]
        technique_by_interval[idx] = erg_technique(pieces)
        interval_summaries[idx] = interval_summary(pieces)
        hr_samples = hr_sample_durations([(s.t, s.hr) for s in group])
        # Per-sample HR only exists for strokes that recorded one (Concept2 w/ a paired HR
        # strap); Garmin-only sessions have no sample-level HR without FIT parsing (not done).
        time_in_zone_by_interval[idx] = time_in_zone(hr_samples, max_hr, settings) if hr_samples else None

    # Drift vs rep 1, by avg split — positive means slower than the first rep.
    rep1_split = interval_summaries[min(interval_summaries)]["avg_split_500m"] if interval_summaries else None
    for summary in interval_summaries.values():
        split = summary["avg_split_500m"]
        summary["drift_vs_rep1_pct"] = ((split - rep1_split) / rep1_split * 100) if (rep1_split and split) else None

    # t/distance reset to 0 at each interval boundary (docs/concept2-endpoints.md); add the
    # running offset from prior intervals so a distance-based chart doesn't saw-tooth back to
    # zero at every rep.
    stroke_dicts = []
    offset_distance = 0.0
    offset_t = 0.0
    last_interval = None
    for s in strokes:
        idx = s.interval_index or 0
        if last_interval is not None and idx != last_interval:
            prev_summary = interval_summaries.get(last_interval, {})
            offset_distance += prev_summary.get("distance_m") or 0.0
            offset_t += prev_summary.get("duration_s") or 0.0
        last_interval = idx
        stroke_dicts.append(
            {
                **s.model_dump(),
                "distance_cum": (s.distance + offset_distance) if s.distance is not None else None,
                "t_cum": s.t + offset_t,
            }
        )

    return {
        "activity_id": activity_id,
        "strokes": stroke_dicts,
        "technique_by_interval": technique_by_interval,
        "interval_summary": interval_summaries,
        "time_in_zone_by_interval": time_in_zone_by_interval,
    }


def _predict_2k(db: Session, settings: dict) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings["predict_lookback_days"])
    stmt = select(Activity).where(
        Activity.source == "concept2",
        Activity.type == "rower",
        Activity.distance.is_not(None),
        Activity.duration.is_not(None),
        Activity.start >= cutoff,
    )
    rows = db.exec(stmt.order_by(Activity.start.desc())).all()

    best_by_bucket: dict[int, dict] = {}
    for a in rows:
        if a.workout_type not in _CONTINUOUS_WORKOUT_TYPES:
            continue
        if not a.distance or a.distance < 1000 or not a.duration:
            continue
        bucket = round(a.distance / 250) * 250
        pace = (a.duration / a.distance) * 500.0
        existing = best_by_bucket.get(bucket)
        if existing is None or pace < existing["pace_s_per_500"]:
            best_by_bucket[bucket] = {
                "distance_m": a.distance,
                "pace_s_per_500": pace,
                "label": a.start.date().isoformat() if a.start else None,
            }
    pieces = sorted(best_by_bucket.values(), key=lambda p: p["distance_m"])[-6:]
    return predict_2k(pieces)


@router.get("/api/predict/2k")
def predict_2k_endpoint(db: Session = Depends(get_db)):
    settings = get_settings(db)
    return _predict_2k(db, settings)


@router.get("/api/settings")
def get_settings_endpoint(db: Session = Depends(get_db)):
    return get_settings(db)


@router.put("/api/settings")
def put_settings(patch: dict = Body(...), db: Session = Depends(get_db)):
    try:
        result = update_settings(db, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    return result


def _estimated_zone_totals(activity: Activity, max_hr: float | None, settings: dict) -> dict[str, float] | None:
    """Fallback for sessions with no per-sample HR (every Garmin-only activity, and any
    Concept2 result synced without a paired HR strap): bucket the *whole* duration into the
    zone for avg_hr, rather than contributing nothing to weekly volume. Callers must flag
    weeks that used this as "estimated" — it's a coarser number than real time-in-zone."""
    zone = zone_for_hr(activity.avg_hr, max_hr, settings)
    if zone is None or not activity.duration:
        return None
    totals = {z: 0.0 for z in ZONE_ORDER}
    totals[zone] = activity.duration
    return totals


@router.get("/api/trends/volume")
def trends_volume(weeks: int = Query(12, ge=1, le=52), db: Session = Depends(get_db)):
    settings = get_settings(db)
    max_hr = settings.get("max_hr")
    today = date.today()
    this_week_start = today - timedelta(days=today.weekday())
    week_starts = [this_week_start - timedelta(weeks=i) for i in range(weeks)][::-1]
    range_start, range_end = week_starts[0], this_week_start + timedelta(days=7)

    stmt = select(Activity).where(
        Activity.start.is_not(None),
        ~((Activity.source == "garmin") & Activity.linked_activity_id.is_not(None)),
    )
    activities = db.exec(stmt).all()

    buckets: dict[date, dict[str, float]] = {w: {z: 0.0 for z in ZONE_ORDER} for w in week_starts}
    estimated_weeks: set[date] = set()
    for a in activities:
        local_date = a.start.astimezone().date()
        if local_date < range_start or local_date >= range_end:
            continue
        bucket_week = local_date - timedelta(days=local_date.weekday())

        exact = None
        if a.source == "concept2":
            # Only the columns time_in_zone actually needs — not whole Stroke rows — to stay
            # memory-bounded on the Pi even with a long training history in range.
            rows = db.exec(
                select(Stroke.t, Stroke.hr, Stroke.interval_index).where(Stroke.activity_id == a.id)
            ).all()
            if rows:
                by_interval: dict[int, list[tuple[float, float | None]]] = {}
                for t, hr, idx in rows:
                    by_interval.setdefault(idx or 0, []).append((t, hr))
                exact = {z: 0.0 for z in ZONE_ORDER}
                for group in by_interval.values():
                    zone_secs = time_in_zone(hr_sample_durations(group), max_hr, settings)
                    for z, secs in zone_secs.items():
                        exact[z] += secs

        if exact is not None:
            for z, secs in exact.items():
                buckets[bucket_week][z] += secs
        else:
            estimated = _estimated_zone_totals(a, max_hr, settings)
            if estimated:
                estimated_weeks.add(bucket_week)
                for z, secs in estimated.items():
                    buckets[bucket_week][z] += secs

    return [{"week_start": w, "zones": buckets[w], "estimated": w in estimated_weeks} for w in week_starts]


_PB_DISTANCES_M = (500, 1000, 2000, 5000, 6000)
_PB_DURATIONS_S = {1800: "30min", 3600: "60min"}


def _pb_entry(activity: Activity | None) -> dict | None:
    if activity is None:
        return None
    pace = (activity.duration / activity.distance) * 500.0 if activity.distance else None
    return {
        "activity_id": activity.id,
        "date": activity.start.date().isoformat() if activity.start else None,
        "distance_m": activity.distance,
        "duration_s": activity.duration,
        "pace_s_per_500": pace,
    }


@router.get("/api/pbs")
def personal_bests(db: Session = Depends(get_db)):
    # type=="rower" only — a SkiErg/BikeErg 2k isn't the same PB, and only continuous
    # workouts (same restriction _predict_2k uses) since interval/piece sets mix rest into
    # duration.
    stmt = select(Activity).where(
        Activity.source == "concept2",
        Activity.type == "rower",
        Activity.distance.is_not(None),
        Activity.duration.is_not(None),
    )
    continuous = [a for a in db.exec(stmt).all() if a.workout_type in _CONTINUOUS_WORKOUT_TYPES]

    result: dict[str, dict | None] = {}
    for target in _PB_DISTANCES_M:
        tolerance = max(25.0, target * 0.02)
        candidates = [a for a in continuous if a.distance and abs(a.distance - target) <= tolerance]
        best = min(candidates, key=lambda a: a.duration) if candidates else None
        result[f"{target}m"] = _pb_entry(best)
    for target, label in _PB_DURATIONS_S.items():
        candidates = [a for a in continuous if a.duration and abs(a.duration - target) <= 30.0]
        best = max(candidates, key=lambda a: a.distance) if candidates else None
        result[label] = _pb_entry(best)
    return result
