from __future__ import annotations

import json
import math
import threading
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from sqlmodel import Session, select

from catch.analytics.body import smooth_weight
from catch.analytics.downsample import bucket_value_bounds, lttb_indices
from catch.analytics.erg_math import w_per_kg
from catch.analytics.predict import predict_2k
from catch.analytics.strain import hr_sample_durations, time_in_zone
from catch.analytics.technique import erg_technique, interval_summary
from catch.analytics.zones import ZONE_ORDER, training_zones, zone_for_hr
from catch.api.deps import as_utc, get_db, require_auth
from catch.coach.memory import next_a_race as _next_a_race
from catch.core.models import Activity, ActivitySamples, CanonicalActivity, DailyScore, DailyWellness, Stroke
from catch.core.settings_store import get_settings, update_settings
from catch.sync import body_comp, rowing_predict
from catch.analytics.samples_codec import unpack_series
from catch.sync.canonical import pick_hr

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
    # `id` stays the raw Concept2 Activity id (GET /api/erg/{id}/strokes needs it);
    # `canonical_id` is what the Today card should navigate to (/workouts/{canonical_id}).
    data["canonical_id"] = row.canonical_id
    return data


@router.get("/api/today")
def today(db: Session = Depends(get_db)):
    today_date = date.today()
    score_row = db.get(DailyScore, today_date)
    wellness = db.get(DailyWellness, today_date)
    recovery = _score_dict(score_row.recovery_json) if score_row else None
    strain = _score_dict(score_row.strain_json) if score_row else None
    load = _score_dict(score_row.load_json) if score_row else None
    rowing_load = _score_dict(score_row.rowing_load_json) if score_row else None
    settings = get_settings(db)

    components = recovery.get("components") if recovery else None
    band_for_targets = (recovery or {}).get("band") or "calibrating"
    strain_target = settings["strain_targets"].get(band_for_targets, settings["strain_targets"]["calibrating"])

    return {
        "date": today_date,
        # Client-side offline/staleness detection used to diff this date against the browser's
        # own local date string, which fires on a plain timezone mismatch regardless of
        # connectivity (server and client calendar days don't line up for several hours a day
        # whenever they're not in the same timezone). An actual timestamp lets the client show
        # real data age without assuming anything about either side's timezone.
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
        # Rowing-only load, parallel to "load"'s all-sport number (task Part B.3) — so
        # cycling/other volume never inflates the figure Today actually trains rowing
        # against.
        "rowing_load": rowing_load,
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
        "next_a_race": _next_a_race(db, today_date),
    }


_ALL_SERIES_METRICS = _WELLNESS_METRICS | set(_SCORE_METRICS) | {"weight", "w_per_kg", "predicted_2k"}


def _metric_series(db: Session, metric: str, from_: date | None, to: date | None) -> list[dict]:
    """One `{date, value, ...}` dict per day/piece for `metric`, shared by GET /api/trends
    (unbounded, from_/to applied at the DB layer) and GET /api/series (fetched once per
    metric with from_=to=None, cached, then range-filtered + LTTB-downsampled in Python —
    see `_cached_full_series` below)."""
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

    raise HTTPException(status_code=400, detail=f"Unknown metric '{metric}'. Allowed: {sorted(_ALL_SERIES_METRICS)}")


@router.get("/api/trends")
def trends(
    metric: str = Query(...),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    db: Session = Depends(get_db),
):
    if metric not in _ALL_SERIES_METRICS:
        raise HTTPException(status_code=400, detail=f"Unknown metric '{metric}'. Allowed: {sorted(_ALL_SERIES_METRICS)}")
    return _metric_series(db, metric, from_, to)


# --- Interactive charts (session 8): GET /api/series -----------------------------------
#
# Caches each metric's *full* history (from_=to=None) — the expensive part is the DB
# scan/join, not the cheap range-filter + downsample done per request below. Keyed on metric
# name only, so a 1GB Pi never holds more than len(_ALL_SERIES_METRICS) series in memory at
# once. Cleared from one place, `invalidate_series_cache()`, called at the end of
# `recompute_scores` (catch/sync/scoring.py) — the single choke point already run after every
# sync, backfill, settings PUT, and note POST (see that file's docstring).
_series_cache_lock = threading.Lock()
_series_cache: dict[str, list[dict]] = {}


def invalidate_series_cache() -> None:
    with _series_cache_lock:
        _series_cache.clear()


def _cached_full_series(db: Session, metric: str) -> list[dict]:
    with _series_cache_lock:
        cached = _series_cache.get(metric)
    if cached is not None:
        return cached
    full = _metric_series(db, metric, None, None)
    with _series_cache_lock:
        _series_cache[metric] = full
    return full


@router.get("/api/series")
def series(
    metrics: str = Query(..., description="Comma-separated metric names, same whitelist as /api/trends"),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    points: int = Query(400, ge=10, le=5000, description="Max points per series; longer ranges are LTTB-downsampled"),
    db: Session = Depends(get_db),
):
    requested = [m.strip() for m in metrics.split(",") if m.strip()]
    unknown = [m for m in requested if m not in _ALL_SERIES_METRICS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown metric(s) {unknown}. Allowed: {sorted(_ALL_SERIES_METRICS)}")

    out: dict[str, dict] = {}
    for metric in requested:
        full = _cached_full_series(db, metric)
        windowed = [p for p in full if (from_ is None or p["date"] >= from_) and (to is None or p["date"] <= to)]
        defined = [p for p in windowed if p.get("value") is not None]

        if not defined:
            out[metric] = {"points": [], "raw_count": 0, "returned_count": 0}
            continue

        xs = [p["date"].toordinal() for p in defined]
        ys = [float(p["value"]) for p in defined]
        indices = lttb_indices(xs, ys, points)
        bounds = bucket_value_bounds(ys, indices)
        extra_keys = sorted({k for p in defined for k in p if k not in ("date", "value")})

        series_points = []
        for pos, idx in enumerate(indices):
            source = defined[idx]
            lo, hi = bounds[pos]
            point = {"date": source["date"].isoformat(), "value": source["value"], "value_min": lo, "value_max": hi}
            for key in extra_keys:
                if key in source:
                    point[key] = source[key]
            series_points.append(point)

        out[metric] = {"points": series_points, "raw_count": len(defined), "returned_count": len(series_points)}

    return {"series": out}


def _date_bounds(from_: date | None, to: date | None) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(from_, datetime.min.time(), tzinfo=timezone.utc) if from_ else None
    end = datetime.combine(to, datetime.max.time(), tzinfo=timezone.utc) if to else None
    return start, end


def _weight_trend(db: Session, from_: date | None, to: date | None) -> list[dict]:
    # Smoothed over *all* history, not just the requested range — otherwise the smoothed
    # line at the start of a narrow range (e.g. "4w") would have no trailing context and
    # read as noisier than it should. One point per day (task Part D.2 — resolve_daily
    # already picked the right source per day; never averaged across scales).
    daily = [d for d in body_comp.resolve_daily(db) if d["weight"] is not None]
    smoothed_by_day = dict(smooth_weight([(d["date"], d["weight"]) for d in daily]))
    out = []
    for d in daily:
        if from_ and d["date"] < from_:
            continue
        if to and d["date"] > to:
            continue
        out.append(
            {
                "date": d["date"],
                "value": d["weight"],
                "smoothed": smoothed_by_day.get(d["date"]),
                "source": d["weight_source"],
            }
        )
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
            # activity_id lets the frontend chart open this exact workout on tap (interaction
            # spec #4) — /api/series already passes any extra per-point keys through verbatim.
            # It's the *canonical* id (session 8/12 — see PLAN.md): /workouts/:id now routes
            # to GET /api/activities/{canonical_id}, never a raw per-source Activity id.
            out.append({"date": a.start.date(), "value": value, "activity_id": a.canonical_id})
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
            out.append({"date": a.start.date(), "value": result["predicted_time_s"], "activity_id": a.canonical_id})
    return out


def _nearest_weight_kg(db: Session, when: datetime | None) -> float | None:
    """Nearest *day's* priority-resolved weight to `when` (task Part D.2 — Withings first,
    Garmin second by default, a manual entry as the last resort) — delegates to
    catch/sync/body_comp.py so this never silently prefers whichever source's row happens to
    sit closer in wall-clock time within the same day."""
    return body_comp.nearest_resolved_weight_kg(db, when)


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
def erg_strokes(
    activity_id: int,
    # Plain `int | None = None` rather than `Query(...)`: catch/coach/tools.py's get_workout
    # calls this function directly (not through a request), bypassing FastAPI's parameter
    # resolution — a Query() object's unresolved default would otherwise be passed through
    # as the literal value of `points` whenever this path is hit without the arg supplied.
    points: int | None = None,
    distance_min: float | None = None,
    distance_max: float | None = None,
    db: Session = Depends(get_db),
):
    if points is not None:
        points = max(20, min(points, 5000))
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

    windowed = [
        s
        for s in stroke_dicts
        if (distance_min is None or (s["distance_cum"] or 0) >= distance_min)
        and (distance_max is None or (s["distance_cum"] or 0) <= distance_max)
    ]
    returned_strokes = windowed
    if points is not None and len(windowed) > points:
        # Downsample on pace_500m (the primary line; split/watts/rate stay x-aligned on the
        # same chosen strokes) — a stroke missing distance_cum can't be placed on the chart's
        # x-axis at all, so it's excluded before LTTB rather than given a fake position.
        placeable = [s for s in windowed if s["distance_cum"] is not None and s["pace_500m"] is not None]
        if len(placeable) > points:
            xs = [s["distance_cum"] for s in placeable]
            ys = [s["pace_500m"] for s in placeable]
            indices = lttb_indices(xs, ys, points)
            returned_strokes = [placeable[i] for i in indices]
        else:
            returned_strokes = placeable

    return {
        "activity_id": activity_id,
        "strokes": returned_strokes,
        "stroke_count": len(stroke_dicts),
        "returned_stroke_count": len(returned_strokes),
        "technique_by_interval": technique_by_interval,
        "interval_summary": interval_summaries,
        "time_in_zone_by_interval": time_in_zone_by_interval,
    }


def _predict_2k(db: Session, settings: dict) -> dict:
    return predict_2k(rowing_predict.recent_rower_pieces(db, settings))


@router.get("/api/predict/2k")
def predict_2k_endpoint(db: Session = Depends(get_db)):
    settings = get_settings(db)
    return _predict_2k(db, settings)


@router.get("/api/settings")
def get_settings_endpoint(db: Session = Depends(get_db)):
    return get_settings(db)


# The exact settings keys resolve_canonical's zones/strain/field-priority pipeline reads
# (catch/sync/canonical.py, catch/analytics/zones.py) — a PUT whose *resulting values* on
# none of these differ from before can't change any already-resolved canonical's cached
# fields, so it can skip the full re-resolve. Compared by value, not by key presence in the
# incoming patch: the Settings page's one Save button always PUTs the whole form (`web/src/
# pages/Settings.tsx`'s `form` state holds every field), so a key-presence check would always
# see every key and never actually skip anything for a real save — caught by a review reading
# the frontend before trusting the first version of this fix. When a relevant value DID
# change, re-timed against a disposable copy of the real local data/catch.db with its real FIT
# samples actually ingested (the first timing pass measured the cheap no-samples path by
# mistake, also caught by review): ~6.5ms/canonical, which over this account's real
# 451-activity history extrapolates to several real seconds on the Pi 3's single ARM core —
# run as a FastAPI background task below instead of inline, so the PUT itself returns
# immediately rather than slowing every other request on that one worker for that long.
_RESOLVE_AFFECTING_SETTINGS_KEYS = {
    "max_hr", "ftp_watts", "field_priority", "zones",
    "trimp_exponent", "min_zone_minutes", "min_zone_pct",
    "auto_trim_enabled", "auto_trim_min_idle_s",
}


def _resolve_all_and_recompute_in_background(engine) -> None:
    """Runs off the request thread (FastAPI BackgroundTasks) with its own DB session — the
    request's `db` session may already be closed by the time this runs. Takes the bound
    engine explicitly (`db.get_bind()`) rather than importing `catch.core.db.engine` directly:
    tests only override the `get_db` *dependency*, not that module-level global, so importing
    it here would silently run against the wrong database under pytest (caught by the test
    suite itself — an `OperationalError` on a column the test engine's schema had but this
    one, pointed at a stale real local DB file, didn't). Must do both steps, in order:
    recompute_scores reads each canonical's *already re-resolved* cached strain_trimp back
    out, so splitting these across sync/background would let a user's immediate GET
    /api/series reflect stale zones/strain until some later, unrelated recompute_scores call
    happens to run."""
    from catch.sync.canonical import resolve_all_canonicals
    from catch.sync.scoring import recompute_scores

    with Session(engine) as session:
        resolve_all_canonicals(session)
        recompute_scores(session)


@router.put("/api/settings")
def put_settings(patch: dict = Body(...), background_tasks: BackgroundTasks = None, db: Session = Depends(get_db)):
    before = get_settings(db)
    try:
        result = update_settings(db, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Session 8/12: a changed max_hr/ftp_watts/field_priority/min_zone_*/auto_trim_* affects
    # every *already-resolved* canonical's cached zones/strain/label/title, none of which
    # run_matching's own resolve calls touch (those only cover orphaned, blank, or
    # newly-merged canonicals).
    if any(before.get(k) != result.get(k) for k in _RESOLVE_AFFECTING_SETTINGS_KEYS):
        background_tasks.add_task(_resolve_all_and_recompute_in_background, db.get_bind())
    else:
        from catch.sync.scoring import recompute_scores

        recompute_scores(db)
    return result


def _estimated_zone_totals(activity: CanonicalActivity, max_hr: float | None, settings: dict) -> dict[str, float] | None:
    """Fallback for a canonical with no per-sample HR cached (nothing parsed a FIT/stroke
    stream for any of its members): bucket the *whole* duration into the zone for avg_hr,
    rather than contributing nothing to weekly volume. Callers must flag weeks that used this
    as "estimated" — it's a coarser number than real time-in-zone."""
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

    # Session 8/12 (see PLAN.md): one row per canonical activity — the matching engine
    # already guarantees that, so no per-source dedup logic is needed here anymore. A
    # canonical's cached zones_json (Part E — real per-sample HR, not the whole-session
    # average) is preferred; only a canonical with no samples at all falls back to the old
    # whole-duration estimate.
    stmt = select(CanonicalActivity).where(CanonicalActivity.start.is_not(None))
    activities = [a for a in db.exec(stmt).all() if not json.loads(a.overrides_json or "{}").get("exclude_from_totals")]

    buckets: dict[date, dict[str, float]] = {w: {z: 0.0 for z in ZONE_ORDER} for w in week_starts}
    estimated_weeks: set[date] = set()
    for a in activities:
        local_date = a.start.astimezone().date()
        if local_date < range_start or local_date >= range_end:
            continue
        bucket_week = local_date - timedelta(days=local_date.weekday())

        exact = None
        if a.zones_json:
            hr_zones = (json.loads(a.zones_json) or {}).get("hr")
            if hr_zones and any(hr_zones.values()):
                exact = hr_zones

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
        # The canonical id — /workouts/:id now always means a canonical, never a raw
        # per-source Activity id (session 8/12, see PLAN.md).
        "activity_id": activity.canonical_id,
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


# -- Per-activity HR/power/cadence samples (task Part E.8) ------------------------------


def _concept2_laps(db: Session, activity_id: int) -> list[dict]:
    """Concept2 has no FIT laps, but Stroke.interval_index boundaries are the same idea —
    reuses the same t-offset accumulation erg_strokes already does for distance."""
    strokes = db.exec(select(Stroke.t, Stroke.interval_index).where(Stroke.activity_id == activity_id).order_by(Stroke.seq)).all()
    if not strokes:
        return []
    by_interval: dict[int, list[float]] = {}
    for t, idx in strokes:
        by_interval.setdefault(idx or 0, []).append(t)
    laps = []
    offset = 0.0
    for idx in sorted(by_interval):
        duration = max(by_interval[idx]) if by_interval[idx] else 0.0
        laps.append({"offset_s": offset, "duration_s": duration})
        offset += duration
    return laps


def _hr_recovery(hr_full: list[float | None], from_offset: int, window_s: int = 60) -> float | None:
    """Drop in HR over `window_s` seconds starting at `from_offset` — used both for "after
    the session" (from_offset = the last work sample) and, generically, after any lap
    boundary. None if the recording doesn't extend far enough past that point to measure it."""
    if from_offset < 0 or from_offset >= len(hr_full):
        return None
    end = from_offset + window_s
    if end >= len(hr_full):
        return None
    start_hr, end_hr = hr_full[from_offset], hr_full[end]
    if start_hr is None or end_hr is None:
        return None
    return start_hr - end_hr


@router.get("/api/activities/{canonical_id}/samples")
def activity_samples(
    canonical_id: int,
    points: int = Query(600, ge=50, le=5000),
    # Plain optional ints, not Query(...) — same reasoning as erg_strokes's distance_min/max:
    # full resolution within a zoomed-in window (task Part E.8's "full resolution when
    # zoomed in"), windowing applied before downsampling so the chart's point budget is
    # spent entirely on the visible range rather than the whole recording.
    start_s: int | None = None,
    end_s: int | None = None,
    db: Session = Depends(get_db),
):
    canonical = db.get(CanonicalActivity, canonical_id)
    if canonical is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    members = db.exec(select(Activity).where(Activity.canonical_id == canonical_id)).all()
    _, _, hr_member = pick_hr(members)
    if hr_member is None:
        hr_member = members[0] if members else None
    if hr_member is None or hr_member.id is None:
        return {"has_data": False, "reason": "no source activity"}

    samples_row = db.get(ActivitySamples, hr_member.id)
    if samples_row is None:
        return {"has_data": False, "reason": "no per-sample data for this activity"}

    n = samples_row.n_samples
    hr_full = unpack_series(samples_row.hr_blob, n)
    power_full = unpack_series(samples_row.power_blob, n)
    cadence_full = unpack_series(samples_row.cadence_blob, n)
    has_hr = any(v is not None for v in hr_full)
    if not has_hr:
        return {"has_data": False, "reason": "no heart-rate data"}

    settings = get_settings(db)
    max_hr = settings.get("max_hr")
    trimmed_s = canonical.auto_trimmed_tail_s or 0
    usable_n = n - int(trimmed_s)

    elapsed = list(range(n))
    # Full recording by default — *including* any auto-trimmed tail, so the frontend can grey
    # it out on the chart (task Part E.8) rather than it just being absent. usable_n only
    # bounds the summary chips/zones/strain above, computed separately.
    window_lo = max(0, start_s) if start_s is not None else 0
    window_hi = min(n, end_s) if end_s is not None else n
    defined_idx = [i for i in range(window_lo, window_hi) if hr_full[i] is not None]
    indices = lttb_indices([elapsed[i] for i in defined_idx], [hr_full[i] for i in defined_idx], points) if defined_idx else []
    chosen = [defined_idx[i] for i in indices]

    laps = json.loads(hr_member.laps_json) if hr_member.laps_json else _concept2_laps(db, hr_member.id)

    defined_hr = [hr_full[i] for i in range(usable_n) if hr_full[i] is not None]
    recoveries = {
        "session_end": _hr_recovery(hr_full, usable_n - 1),
        "per_lap": [
            {"offset_s": lap["offset_s"], "recovery_bpm": _hr_recovery(hr_full, int(lap["offset_s"] + lap["duration_s"]))}
            for lap in laps
        ],
    }

    return {
        "has_data": True,
        "canonical_id": canonical_id,
        "n_samples": n,
        "usable_n_samples": usable_n,
        "trimmed_tail_s": trimmed_s,
        "max_hr_setting": max_hr,
        "avg_hr": (sum(defined_hr) / len(defined_hr)) if defined_hr else None,
        "max_hr_observed": max(defined_hr) if defined_hr else None,
        "min_hr_observed": min(defined_hr) if defined_hr else None,
        "zones": json.loads(canonical.zones_json) if canonical.zones_json else None,
        "zones_config": training_zones(max_hr=max_hr, settings=settings),
        "session_label": canonical.session_label,
        "laps": laps,
        "hr_recovery": recoveries,
        "points": [
            {
                "elapsed_s": elapsed[i],
                "hr": hr_full[i],
                "power": power_full[i],
                "cadence": cadence_full[i],
            }
            for i in chosen
        ],
        "returned_count": len(chosen),
        "raw_count": len(defined_idx),
    }
