from __future__ import annotations

"""Shared "recent best Concept2 pieces" gathering, used by GET /api/predict/2k
(catch/api/routes_analytics.py) and by catch/sync/canonical.py's erg power-zone threshold
(task Part E.5 — needs a watts-at-2k-pace number, not just the predicted time)."""

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from catch.analytics.erg_math import watts_from_pace
from catch.analytics.predict import predict_2k
from catch.core.models import Activity

# Interval/piece workouts mix work+rest into Activity.duration while distance stays
# work-only (docs/concept2-endpoints.md) — Paul's law needs a clean distance/time pair.
CONTINUOUS_WORKOUT_TYPES = {None, "unknown", "JustRow", "FixedDistanceSplits", "FixedTimeSplits"}


def recent_rower_pieces(session: Session, settings: dict) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings["predict_lookback_days"])
    stmt = select(Activity).where(
        Activity.source == "concept2",
        Activity.type == "rower",
        Activity.distance.is_not(None),
        Activity.duration.is_not(None),
        Activity.start >= cutoff,
    )
    rows = session.exec(stmt.order_by(Activity.start.desc())).all()

    best_by_bucket: dict[int, dict] = {}
    for a in rows:
        if a.workout_type not in CONTINUOUS_WORKOUT_TYPES:
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
    return sorted(best_by_bucket.values(), key=lambda p: p["distance_m"])[-6:]


def rowing_watts_2k(session: Session, settings: dict) -> float | None:
    """Predicted 2k pace (Paul's law over recent qualifying pieces), converted to watts —
    the erg power-zone threshold Part E.5 needs. None until enough history exists."""
    result = predict_2k(recent_rower_pieces(session, settings))
    if result["value"] is None:
        return None
    return watts_from_pace(result["value"])
