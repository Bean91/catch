from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlmodel import Session, select

from catch.analytics.erg_math import w_per_kg
from catch.analytics.predict import predict_2k
from catch.analytics.strain import time_in_zone
from catch.analytics.technique import erg_technique
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


@router.get("/api/today")
def today(db: Session = Depends(get_db)):
    today_date = date.today()
    score_row = db.get(DailyScore, today_date)
    wellness = db.get(DailyWellness, today_date)
    recovery = _score_dict(score_row.recovery_json) if score_row else None
    strain = _score_dict(score_row.strain_json) if score_row else None
    load = _score_dict(score_row.load_json) if score_row else None
    return {
        "date": today_date,
        "recovery": recovery,
        "sleep_last_night": {"seconds": wellness.sleep_seconds, "score": wellness.sleep_score} if wellness else None,
        "strain_today": strain,
        "load": load,
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
        return [{"date": r.date, "value": (_score_dict(getattr(r, field)) or {}).get("value")} for r in rows]

    allowed = sorted(_WELLNESS_METRICS | set(_SCORE_METRICS))
    raise HTTPException(status_code=400, detail=f"Unknown metric '{metric}'. Allowed: {allowed}")


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


def _hr_samples(strokes: list[Stroke]) -> list[tuple[float, float]]:
    """Duration of each HR reading = t minus the previous stroke's t (first stroke in the
    interval gets its own t). Walks every stroke to track t correctly even when some strokes
    in between have no hr reading."""
    samples = []
    prev_t: float | None = None
    for s in strokes:
        duration = s.t if prev_t is None else max(0.0, s.t - prev_t)
        if s.hr is not None:
            samples.append((duration, s.hr))
        prev_t = s.t
    return samples


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
    for idx, group in by_interval.items():
        pieces = [
            {"t": s.t, "distance": s.distance, "watts": s.watts, "stroke_rate": s.stroke_rate, "pace_500m": s.pace_500m}
            for s in group
        ]
        technique_by_interval[idx] = erg_technique(pieces)
        hr_samples = _hr_samples(group)
        # Per-sample HR only exists for strokes that recorded one (Concept2 w/ a paired HR
        # strap); Garmin-only sessions have no sample-level HR without FIT parsing (not done).
        time_in_zone_by_interval[idx] = time_in_zone(hr_samples, max_hr, settings) if hr_samples else None

    return {
        "activity_id": activity_id,
        "strokes": strokes,
        "technique_by_interval": technique_by_interval,
        "time_in_zone_by_interval": time_in_zone_by_interval,
    }


@router.get("/api/predict/2k")
def predict_2k_endpoint(db: Session = Depends(get_db)):
    settings = get_settings(db)
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
