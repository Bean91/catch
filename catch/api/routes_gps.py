from __future__ import annotations

"""Session 20 (docs/analytics.md §28): GPS track, on-water metrics, weather and route endpoints.

The `build_*` functions hold the logic and take an explicit Session so the coach tools can call
them directly (the same delegation precedent as get_tests -> routes_tests); the route handlers
are thin wrappers. Every figure carries a `source` — "gps_derived" (computed here from the
device's own fixes), "provider" (what Garmin reported) or "manual" (the athlete's own entry) — and
a missing value stays None rather than being estimated.

Precise coordinates are returned by these REST endpoints (the map needs them) but never by the
coach tools' `get_route`, which sends only an area and summary figures to the AI provider.
"""

import json
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from catch.analytics.gps import (
    bounds as track_bounds,
    build_series,
    compute_metrics,
    compute_splits,
    default_split_m,
    detect_on_water,
    lap_metrics,
    likely_rowing,
    pace_for,
)
from catch.api.deps import get_db, require_auth
from catch.core.models import Activity, ActivityTrack, CanonicalActivity, Route
from catch.core.settings_store import get_settings
from catch.sync import routes as route_sync
from catch.sync import tracks as track_sync
from catch.sync import weather as weather_sync

router = APIRouter(dependencies=[Depends(require_auth)])


def _canonical(db: Session, canonical_id: int) -> CanonicalActivity:
    canonical = db.get(CanonicalActivity, canonical_id)
    if canonical is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    return canonical


def track_member(db: Session, canonical_id: int) -> tuple[CanonicalActivity, Optional[Activity], Optional[ActivityTrack], str]:
    """The member that carries a usable GPS track, plus a reason code when none does.
    reasons: no_gps_recorded (a FIT was parsed and had no fixes — e.g. an indoor erg),
    not_processed (no FIT parsed yet), too_few_fixes."""
    canonical = _canonical(db, canonical_id)
    members = db.exec(select(Activity).where(Activity.canonical_id == canonical_id).order_by(Activity.id)).all()
    seen_empty = False
    for m in members:
        row = db.get(ActivityTrack, m.id)
        if row is None:
            continue
        if row.n_points >= 2:
            return canonical, m, row, "ok"
        seen_empty = True
    return canonical, None, None, ("no_gps_recorded" if seen_empty else "not_processed")


_REASON_TEXT = {
    "no_gps_recorded": "No GPS track was recorded for this activity.",
    "not_processed": "No GPS data has been read for this activity (no FIT file synced yet).",
    "too_few_fixes": "Too few valid GPS fixes survived filtering to measure anything.",
}


def _no_track(reason: str) -> dict:
    return {"has_track": False, "reason": reason, "message": _REASON_TEXT.get(reason, reason)}


def _ow(db: Session) -> dict:
    return get_settings(db)["on_water"]


def build_track(db: Session, canonical_id: int, points: int = 600) -> dict:
    canonical, activity, row, reason = track_member(db, canonical_id)
    if row is None:
        return _no_track(reason)
    ft = track_sync.filtered_for(db, activity, row)
    if ft is None:
        return _no_track("too_few_fixes")
    series = build_series(ft, points, canonical.sport_family)
    report = {**ft.report, "records_total": row.n_records, "records_without_fix": row.n_records - row.n_points,
              "accuracy_reported": row.acc_blob is not None}
    return {
        "has_track": True,
        "activity_id": activity.id,
        "sport_family": canonical.sport_family,
        "pace_unit": series[0]["pace_unit"],
        "points": series,
        "returned_count": len(series),
        "accepted_count": len(ft.t),
        "bounds": track_bounds(ft),
        "start": {"lat": ft.lat[0], "lon": ft.lon[0]},
        "end": {"lat": ft.lat[-1], "lon": ft.lon[-1]},
        "has_elevation": row.alt_blob is not None,
        "has_hr": row.hr_blob is not None,
        "filter_report": report,
        "provenance": {
            "track": "Garmin FIT position fixes, stored as recorded",
            "speed_pace_distance": "gps_derived",
            "elevation_hr": "provider",
        },
    }


SPLIT_M_MIN, SPLIT_M_MAX, SPLIT_ROWS_MAX = 50.0, 10000.0, 400


def build_on_water(db: Session, canonical_id: int, split_m: Optional[float] = None) -> dict:
    # Checked here, not only in the REST Query, so the coach/MCP path can't ask for thousands of rows.
    if split_m is not None and not (SPLIT_M_MIN <= float(split_m) <= SPLIT_M_MAX):
        raise ValueError(f"split_m must be between {SPLIT_M_MIN:.0f} and {SPLIT_M_MAX:.0f} metres")
    canonical, activity, row, reason = track_member(db, canonical_id)
    members = db.exec(select(Activity).where(Activity.canonical_id == canonical_id)).all()
    primary = activity or (members[0] if members else None)
    detection = detect_on_water(primary.source, primary.type, activity is not None) if primary else {"kind": "unknown", "basis": "none"}
    # the canonical's category is authoritative for rowing; `detection` shows what the source said
    detection["category"] = canonical.category
    if row is None:
        return {**_no_track(reason), "detection": detection}

    ow = _ow(db)
    ft = track_sync.filtered_for(db, activity, row)
    if ft is None:
        return {**_no_track("too_few_fixes"), "detection": detection}
    provider = json.loads(row.provider_json) if row.provider_json else {}
    metrics = compute_metrics(ft, provider, ow)
    split = float(split_m) if split_m else default_split_m(canonical.sport_family, ow)
    total_m = ft.cum_dist[-1]
    if total_m / split > SPLIT_ROWS_MAX:
        raise ValueError(f"split_m={split:.0f} would produce more than {SPLIT_ROWS_MAX} splits for this activity; use a larger split")
    splits = compute_splits(ft, split, ow)
    for s in splits["splits"]:
        s["pace"] = pace_for(s["speed_mps"], canonical.sport_family)
        s["source"] = "gps_derived"
    avg = metrics["avg_speed_mps"]["value"]
    laps = json.loads(row.laps_json) if row.laps_json else []
    out = {
        "has_track": True,
        "activity_id": activity.id,
        "sport_family": canonical.sport_family,
        "detection": detection,
        "metrics": metrics,
        "pace": {**pace_for(avg, canonical.sport_family), "source": "gps_derived",
                 "method": "from average moving speed"},
        "splits": {**splits, "source": "gps_derived",
                   "method": "boundary time interpolated between fixes at each multiple of split_m"},
        "laps": {
            "usable": len(laps) >= 2,
            "count": len(laps),
            "rows": lap_metrics(ft, laps) if len(laps) >= 2 else [],
            "note": None if len(laps) >= 2 else "Only one lap recorded — no lap or interval breakdown to show.",
        },
        "route": route_sync.route_for_activity(db, activity),
        "weather": route_sync.weather_brief(db, activity.id),
        "environment_corrected": False,
        "environment_note": "Speed and pace are raw GPS figures. They are not corrected for wind, "
                            "current or water conditions.",
    }
    if detection["kind"] == "unknown":
        cad = canonical.avg_cadence
        out["likely_rowing"] = {
            "value": likely_rowing(cad, avg), "kind": "inference",
            "basis": "stroke-rate-like cadence and boat-like speed on an activity not typed as rowing",
        }
    return out


def build_weather(db: Session, canonical_id: int) -> dict:
    canonical, activity, row, reason = track_member(db, canonical_id)
    if row is None:
        return {"status": "no_gps", "reason": reason, "message": _REASON_TEXT.get(reason, reason),
                "weather": None, "attribution": weather_sync.ATTRIBUTION, "attribution_url": weather_sync.ATTRIBUTION_URL}
    return {"activity_id": activity.id, **weather_sync.weather_payload(db, activity.id)}


def build_route_summary(db: Session, canonical_id: int) -> dict:
    """Coach-facing: a summary and a coarse area, never coordinates."""
    canonical, activity, row, reason = track_member(db, canonical_id)
    if row is None:
        return _no_track(reason)
    summary = json.loads(row.summary_json) if row.summary_json else {}
    prov = json.loads(row.provider_json) if row.provider_json else {}
    b = summary.get("bounds") or {}
    area = None
    if b:
        area = {
            "place_name": prov.get("location_name"),
            "approx_center": {"lat": round((b["min_lat"] + b["max_lat"]) / 2, 1),
                              "lon": round((b["min_lon"] + b["max_lon"]) / 2, 1)},
            "note": "Coordinates are rounded to 0.1 degree; the exact track is not shared with the coach.",
        }
    return {
        "has_track": True,
        "activity_id": activity.id,
        "sport_family": canonical.sport_family,
        "area": area,
        "gps_distance_m": {"value": summary.get("distance_m"), "source": "gps_derived"},
        "moving_s": {"value": summary.get("moving_s"), "source": "gps_derived"},
        "avg_speed_mps": {"value": summary.get("avg_speed_mps"), "source": "gps_derived"},
        "provider_distance_m": {"value": prov.get("distance_m"), "source": "provider"},
        "filter_report": summary.get("filter_report"),
        "route": route_sync.route_for_activity(db, activity),
    }


def build_route_history(db: Session, route_id: int) -> dict:
    route = db.get(Route, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return route_sync.route_history(db, route)


# ---- handlers -------------------------------------------------------------------------------

@router.get("/api/activities/{canonical_id}/track")
def get_track(canonical_id: int, points: int = Query(600, ge=50, le=5000), db: Session = Depends(get_db)):
    return build_track(db, canonical_id, points)


@router.get("/api/activities/{canonical_id}/on-water")
def get_on_water(canonical_id: int, split_m: Optional[float] = Query(None, ge=50, le=10000), db: Session = Depends(get_db)):
    try:
        return build_on_water(db, canonical_id, split_m)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/activities/{canonical_id}/weather")
def get_weather(canonical_id: int, db: Session = Depends(get_db)):
    return build_weather(db, canonical_id)


@router.post("/api/activities/{canonical_id}/weather/refresh")
def refresh_weather(canonical_id: int, db: Session = Depends(get_db)):
    _, activity, row, reason = track_member(db, canonical_id)
    if row is None:
        raise HTTPException(status_code=409, detail=_REASON_TEXT.get(reason, "No GPS track"))
    if not _ow(db)["weather_enabled"]:
        raise HTTPException(status_code=409, detail="Weather lookup is turned off in settings.")
    result = weather_sync.ensure_weather(db, activity, force=True)
    if result is None:
        raise HTTPException(status_code=503, detail="The weather provider could not be reached; nothing was changed.")
    return build_weather(db, canonical_id)


class RouteAssignRequest(BaseModel):
    route_id: Optional[int] = None
    unpin: bool = False
    new_route: bool = False
    name: Optional[str] = None


@router.put("/api/activities/{canonical_id}/route")
def put_activity_route(canonical_id: int, body: RouteAssignRequest, db: Session = Depends(get_db)):
    canonical, activity, row, reason = track_member(db, canonical_id)
    if row is None:
        raise HTTPException(status_code=409, detail=_REASON_TEXT.get(reason, "No GPS track"))
    if canonical.sport_family != "rowing":
        raise HTTPException(status_code=409, detail="Routes are only formed for rowing sessions.")
    try:
        if body.unpin:
            route_sync.unpin_route(db, activity)
        elif body.new_route:
            route_sync.create_route_from_activity(db, activity, body.name)
        else:
            route_sync.set_route(db, activity, body.route_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    return {"route": route_sync.route_for_activity(db, activity)}


@router.get("/api/routes")
def list_routes(db: Session = Depends(get_db)):
    return {"routes": route_sync.list_routes(db)}


@router.get("/api/routes/{route_id}")
def get_route_detail(route_id: int, db: Session = Depends(get_db)):
    route = db.get(Route, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    n = len(db.exec(select(ActivityTrack).where(ActivityTrack.route_id == route_id)).all())
    return {**route_sync.route_payload(route, n), "reference": json.loads(route.signature_json)}


class RouteEditRequest(BaseModel):
    name: Optional[str] = None
    tags: Optional[list[str]] = None


@router.patch("/api/routes/{route_id}")
def patch_route(route_id: int, body: RouteEditRequest = Body(...), db: Session = Depends(get_db)):
    route = db.get(Route, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    fields = body.model_fields_set
    route_sync.update_route(db, route, name=body.name, tags=body.tags, set_name="name" in fields)
    return get_route_detail(route_id, db)


@router.get("/api/routes/{route_id}/history")
def get_route_history_endpoint(route_id: int, db: Session = Depends(get_db)):
    return build_route_history(db, route_id)
