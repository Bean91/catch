from __future__ import annotations

"""The DB-facing half of GPS tracks (session 20, docs/analytics.md §28): store a streamed FIT
track as compact blobs, decode it back, and cache the derived summary route matching reads.
The pure filtering/metrics live in catch/analytics/gps.py."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from catch.analytics.gps import (
    FilteredTrack,
    RawTrack,
    bounds,
    compute_metrics,
    filter_track,
    speed_ceiling_mps,
)
from catch.analytics.samples_codec import (
    pack_int32_delta,
    pack_scaled,
    pack_series,
    pack_uint32,
    unpack_int32_delta,
    unpack_scaled,
    unpack_series,
    unpack_uint32,
)
from catch.analytics.matching import sport_family as _sport_family
from catch.core.models import Activity, ActivityTrack
from catch.core.settings_store import get_settings
from catch.sync.fit_parse import FitTrack, parse_fit_track

logger = logging.getLogger("catch.tracks")

_DEG = 1e7
_ALT_SCALE, _ALT_OFFSET = 10.0, 500.0


def family_of(activity: Activity) -> Optional[str]:
    """`Activity.sport_family` is NULL on rows that predate that column (the migration adds it
    empty), so derive it from source+type the same way upsert does when it's missing — reading the
    column directly silently disabled routes and picked the wrong speed ceiling for old rows."""
    return activity.sport_family or _sport_family(activity.source, activity.type)


def _first(*values):
    for v in values:
        if v is not None:
            return v
    return None


def provider_figures(activity: Activity, fit_session: Optional[dict]) -> dict:
    """What Garmin itself reported — the activity summary first, the FIT session message as a
    fallback. Kept apart from every derived figure and always labelled source 'provider'."""
    raw: dict = {}
    if activity.raw_json:
        try:
            raw = json.loads(activity.raw_json)
        except ValueError:
            raw = {}
    s = fit_session or {}
    return {
        "distance_m": _first(raw.get("distance"), s.get("total_distance_m"), activity.distance),
        "moving_s": _first(raw.get("movingDuration"), s.get("timer_s")),
        "elapsed_s": _first(raw.get("elapsedDuration"), s.get("elapsed_s"), raw.get("duration")),
        "avg_speed_mps": _first(raw.get("averageSpeed"), s.get("avg_speed_mps")),
        "max_speed_mps": _first(raw.get("maxSpeed"), s.get("max_speed_mps")),
        "location_name": raw.get("locationName"),
    }


def _encode(parsed: FitTrack) -> dict:
    has_alt = any(v is not None for v in parsed.alt)
    has_acc = any(v is not None for v in parsed.acc)
    has_hr = any(v is not None for v in parsed.hr)
    return {
        "t_blob": pack_uint32([int(round(v)) for v in parsed.t]),
        "lat_blob": pack_int32_delta([int(round(v * _DEG)) for v in parsed.lat]),
        "lon_blob": pack_int32_delta([int(round(v * _DEG)) for v in parsed.lon]),
        "dist_blob": pack_uint32([None if v is None else int(round(v * 100)) for v in parsed.dist]),
        "speed_blob": pack_scaled(parsed.speed, 100.0),
        "alt_blob": pack_scaled(parsed.alt, _ALT_SCALE, _ALT_OFFSET) if has_alt else None,
        "hr_blob": pack_series(parsed.hr) if has_hr else None,
        "acc_blob": pack_scaled(parsed.acc, 100.0) if has_acc else None,
    }


def load_raw_track(row: ActivityTrack) -> Optional[RawTrack]:
    """Decodes the stored blobs. Bounded by one activity's record count (a few thousand)."""
    n = row.n_points
    if n < 1:
        return None
    t = unpack_uint32(row.t_blob, n)
    lat = unpack_int32_delta(row.lat_blob, n)
    lon = unpack_int32_delta(row.lon_blob, n)
    dist = unpack_uint32(row.dist_blob, n)
    return RawTrack(
        t=[float(v) if v is not None else 0.0 for v in t],
        lat=[None if v is None else v / _DEG for v in lat],
        lon=[None if v is None else v / _DEG for v in lon],
        speed=unpack_scaled(row.speed_blob, n, 100.0),
        dist=[None if v is None else v / 100.0 for v in dist],
        alt=unpack_scaled(row.alt_blob, n, _ALT_SCALE, _ALT_OFFSET),
        hr=unpack_series(row.hr_blob, n),
    )


def filtered_for(session: Session, activity: Activity, row: ActivityTrack) -> Optional[FilteredTrack]:
    raw = load_raw_track(row)
    if raw is None:
        return None
    ow = get_settings(session)["on_water"]
    return filter_track(raw, speed_ceiling_mps(activity.type, family_of(activity), ow), ow)


def summarize(session: Session, activity: Activity, row: ActivityTrack) -> Optional[dict]:
    """The cached figures route history reads without ever decoding a blob."""
    ft = filtered_for(session, activity, row)
    if ft is None:
        return None
    ow = get_settings(session)["on_water"]
    provider = json.loads(row.provider_json) if row.provider_json else {}
    m = compute_metrics(ft, provider, ow)
    hrs = [h for h in ft.hr if h is not None]
    elapsed = m["elapsed_s"]["value"] or 0.0
    return {
        "n_points": len(ft.t),
        "distance_m": m["distance_m"]["value"],
        "moving_s": m["moving_s"]["value"],
        "elapsed_s": elapsed,
        "t_start_s": ft.t[0],
        "t_end_s": ft.t[-1],
        "avg_speed_mps": m["avg_speed_mps"]["value"],
        "peak_speed_mps": m["peak_speed_mps"]["value"],
        "avg_hr": (sum(hrs) / len(hrs)) if hrs else None,
        "gap_fraction": (ft.report["gap_seconds"] / (elapsed + ft.report["gap_seconds"])) if elapsed else 0.0,
        "bounds": bounds(ft),
        "start": [ft.lat[0], ft.lon[0]],
        "end": [ft.lat[-1], ft.lon[-1]],
        "filter_report": ft.report,
    }


def store_track(session: Session, activity: Activity, parsed: FitTrack) -> ActivityTrack:
    row = session.get(ActivityTrack, activity.id)
    if row is None:
        row = ActivityTrack(activity_id=activity.id, start=parsed.start)
    row.start = parsed.start
    row.n_records = parsed.n_records
    row.n_points = len(parsed.t)
    for col in ("t_blob", "lat_blob", "lon_blob", "dist_blob", "speed_blob", "alt_blob", "hr_blob", "acc_blob"):
        setattr(row, col, None)
    row.laps_json = json.dumps(parsed.laps) if parsed.laps else None
    row.provider_json = json.dumps(provider_figures(activity, parsed.session))
    if parsed.t:
        for col, blob in _encode(parsed).items():
            setattr(row, col, blob)
    row.summary_json = None
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    if row.n_points >= 2:
        summary = summarize(session, activity, row)
        if summary is not None:
            from catch.sync.routes import attach_signature

            attach_signature(summary, session, activity, row)
            row.summary_json = json.dumps(summary)
            session.add(row)
            session.commit()
            try:
                from catch.sync.routes import assign_route

                assign_route(session, activity)
            except Exception:
                logger.warning("route assignment failed for activity %s", activity.id, exc_info=True)
                session.rollback()
    return row


def ingest_track(session: Session, activity: Activity, *, force: bool = False) -> Optional[ActivityTrack]:
    """Parses the activity's FIT file once. Returns the stored row, or None when there is no FIT
    file to read. A parse failure writes nothing (so the next sync retries)."""
    if not force:
        existing = session.get(ActivityTrack, activity.id)
        if existing is not None:
            return existing
    if not activity.fit_path or not Path(activity.fit_path).exists():
        return None
    parsed = parse_fit_track(activity.fit_path)
    if parsed is None:
        return None
    return store_track(session, activity, parsed)


def backfill_tracks(session: Session, *, force: bool = False) -> dict:
    """Every Garmin activity whose FIT file is on disk and has no track row yet (or all of them
    with force). Streams one file at a time."""
    done = with_gps = skipped = 0
    for activity in session.exec(select(Activity).where(Activity.fit_path.is_not(None))).all():  # type: ignore[union-attr]
        try:
            row = ingest_track(session, activity, force=force)
        except Exception:
            logger.exception("track backfill failed for activity %s", activity.id)
            session.rollback()
            skipped += 1
            continue
        if row is None:
            skipped += 1
            continue
        done += 1
        if row.n_points >= 2:
            with_gps += 1
    return {"parsed": done, "with_gps": with_gps, "skipped": skipped}
