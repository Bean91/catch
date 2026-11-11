from __future__ import annotations

"""The DB-facing half of weather (session 20, docs/analytics.md §28.5, docs/weather-endpoints.md):
the per-cell-per-UTC-day cache, matching a cached day to an activity's window, and a bounded
enrichment pass. The pure interpolation/aggregation is catch/analytics/weather.py; the HTTP is
catch/sync/weather_client.py."""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from catch.analytics.weather import status_for, summarize_window, to_utc_ts, utc_dates_needed
from catch.core.models import Activity, ActivityTrack, ActivityWeather, WeatherCell
from catch.core.settings_store import get_settings
from catch.sync.weather_client import (
    ATTRIBUTION,
    ATTRIBUTION_URL,
    PROVIDER,
    OpenMeteoClient,
)

logger = logging.getLogger("catch.weather")

# A provisional day (newer than the reanalysis delay) is re-fetched at most this often...
PROVISIONAL_TTL = timedelta(hours=12)
# ...and a day that is still incomplete a month later is left alone: re-asking won't change it.
GIVE_UP_AFTER_DAYS = 30

DISCLAIMER = (
    "Gridded model/reanalysis data for the area (roughly 9-25 km cells), not a measurement taken "
    "at the water. Shown as context only — never as a performance correction."
)


def cell_for(lat: float, lon: float) -> tuple[int, int]:
    """Tenths of a degree. Rounding happens here, before anything is sent anywhere."""
    return round(lat * 10), round(lon * 10)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _needs_refetch(row: Optional[WeatherCell], day: date, now: datetime) -> bool:
    if row is None:
        return True
    if row.complete:
        return False
    if (now.date() - day).days >= GIVE_UP_AFTER_DAYS:
        return False
    return now - _aware(row.fetched_at) >= PROVISIONAL_TTL


def get_cell_day(
    session: Session, client: OpenMeteoClient, lat_e1: int, lon_e1: int, day: date, now: datetime
) -> tuple[Optional[WeatherCell], bool]:
    """(cell, fetch_failed). The cached cell-day, fetching only when there is none or it is
    provisional and stale. On a failed fetch the stale row (if any) is returned rather than nothing,
    with fetch_failed True so the caller never mistakes it for a refresh."""
    row = session.exec(
        select(WeatherCell).where(
            WeatherCell.provider == PROVIDER,
            WeatherCell.lat_e1 == lat_e1,
            WeatherCell.lon_e1 == lon_e1,
            WeatherCell.utc_date == day,
        )
    ).first()
    if not _needs_refetch(row, day, now):
        return row, False
    data = client.fetch_day(lat_e1, lon_e1, day)
    if data is None:
        return row, True
    if row is None:
        row = WeatherCell(provider=PROVIDER, lat_e1=lat_e1, lon_e1=lon_e1, utc_date=day)
    row.hourly_json = json.dumps({str(ts): v for ts, v in data["hourly"].items()})
    row.complete = bool(data["complete"])
    row.grid_lat, row.grid_lon, row.grid_elevation = data["grid_lat"], data["grid_lon"], data["elevation"]
    row.fetched_at = now
    session.add(row)
    session.commit()
    return row, False


def _hourly_from(cells: list[WeatherCell]) -> dict[int, dict]:
    merged: dict[int, dict] = {}
    for c in cells:
        for ts, row in json.loads(c.hourly_json or "{}").items():
            merged[int(ts)] = row
    return merged


def ensure_weather(
    session: Session,
    activity: Activity,
    client: Optional[OpenMeteoClient] = None,
    *,
    force: bool = False,
    now: Optional[datetime] = None,
) -> Optional[ActivityWeather]:
    """Matches weather to one activity's GPS window and stores the result. Returns None (and
    writes nothing, so a later pass retries) when weather is off, the activity has no usable
    track, or the provider couldn't be reached. An activity with a window but no provider data
    gets an explicit 'unavailable' row, never invented figures."""
    now = now or datetime.now(timezone.utc)
    if not get_settings(session)["on_water"]["weather_enabled"]:
        return None
    track = session.get(ActivityTrack, activity.id)
    if track is None or track.n_points < 2 or not track.summary_json:
        return None
    summary = json.loads(track.summary_json)
    if "t_start_s" not in summary:
        return None

    existing = session.get(ActivityWeather, activity.id)
    if existing is not None and existing.status == "ok" and not force:
        return existing

    base = to_utc_ts(track.start)
    start_ts, end_ts = base + summary["t_start_s"], base + summary["t_end_s"]
    if end_ts <= start_ts or end_ts > now.timestamp():
        return existing
    b = summary["bounds"]
    lat_e1, lon_e1 = cell_for((b["min_lat"] + b["max_lat"]) / 2, (b["min_lon"] + b["max_lon"]) / 2)

    client = client or OpenMeteoClient()
    cells = []
    any_failed = False
    for day in utc_dates_needed(start_ts, end_ts):
        cell, failed = get_cell_day(session, client, lat_e1, lon_e1, day, now)
        any_failed = any_failed or failed
        if cell is not None:
            cells.append(cell)
    if not cells:
        return existing  # provider unreachable: write nothing, retry later
    if any_failed and existing is not None:
        # A refresh that couldn't happen is not a refresh: leave the row (and its fetched_at, which
        # drives the retry TTL) exactly as it was. An explicit "Refresh" gets None -> an honest 503.
        return None if force else existing

    result = summarize_window(_hourly_from(cells), start_ts, end_ts)
    provisional = any(not c.complete for c in cells)
    status = status_for(result, provisional)
    result["provisional"] = provisional
    result["location_rounded"] = {"lat": lat_e1 / 10.0, "lon": lon_e1 / 10.0}
    result["grid"] = [
        {"utc_date": c.utc_date.isoformat(), "lat": c.grid_lat, "lon": c.grid_lon, "elevation_m": c.grid_elevation}
        for c in cells
    ]
    row = existing or ActivityWeather(activity_id=activity.id, status=status, provider=PROVIDER)
    row.status, row.provider = status, PROVIDER
    row.summary_json = json.dumps(result)
    row.attribution = ATTRIBUTION
    row.lat_e1, row.lon_e1 = lat_e1, lon_e1
    row.fetched_at = now
    session.add(row)
    session.commit()
    return row


def weather_payload(session: Session, activity_id: int) -> dict:
    """What the API and the coach tools return. Observed provider data and its provenance are
    separate from any reading of it; a missing row says so rather than returning empty fields."""
    base = {
        "provider": PROVIDER,
        "attribution": ATTRIBUTION,
        "attribution_url": ATTRIBUTION_URL,
        "disclaimer": DISCLAIMER,
        "source": "provider_reanalysis",
    }
    row = session.get(ActivityWeather, activity_id)
    if row is None:
        return {**base, "status": "not_fetched", "weather": None}
    return {
        **base,
        "status": row.status,
        "fetched_at": _aware(row.fetched_at).isoformat(),
        "weather": json.loads(row.summary_json),
    }


def _eligible(track: ActivityTrack, now: datetime) -> bool:
    """A track weather can actually be matched to: a cached summary with a window that has ended.
    Without this an erg file that picked up a couple of stray fixes (no summary) would be retried
    forever, since ensure_weather can never write anything for it."""
    if track.n_points < 2 or not track.summary_json:
        return False
    summary = json.loads(track.summary_json)
    if "t_start_s" not in summary:
        return False
    end_ts = to_utc_ts(track.start) + summary["t_end_s"]
    return end_ts > to_utc_ts(track.start) + summary["t_start_s"] and end_ts <= now.timestamp()


def _pending(session: Session, now: datetime) -> list[ActivityTrack]:
    out = []
    tracks = session.exec(
        select(ActivityTrack).where(ActivityTrack.n_points >= 2).order_by(ActivityTrack.start.desc())  # type: ignore[union-attr]
    ).all()
    for track in tracks:
        if not _eligible(track, now):
            continue
        existing = session.get(ActivityWeather, track.activity_id)
        if existing is not None and existing.status == "ok":
            continue
        out.append(track)
    return out


def pending_count(session: Session, now: Optional[datetime] = None) -> int:
    return len(_pending(session, now or datetime.now(timezone.utc)))


def enrich_pending(
    session: Session, client: Optional[OpenMeteoClient] = None, *, limit: int = 20, now: Optional[datetime] = None
) -> dict:
    """Weather for GPS activities that have none yet, or whose result is still provisional. Bounded
    per run so a first backfill spreads across several sync passes instead of one long burst.

    `processed` counts only rows actually written — a pass that wrote nothing reports 0, which is
    what lets a caller loop until done without spinning when the provider is unreachable or the
    request budget is spent. The pass stops at the first such failure: later calls would fail the
    same way, and retrying them just burns the budget."""
    now = now or datetime.now(timezone.utc)
    if not get_settings(session)["on_water"]["weather_enabled"]:
        return {"processed": 0, "ok": 0, "disabled": True}
    client = client or OpenMeteoClient()
    done = ok = 0
    stopped = None
    for track in _pending(session, now):
        if done >= limit:
            break
        existing = session.get(ActivityWeather, track.activity_id)
        if existing is not None and now - _aware(existing.fetched_at) < PROVISIONAL_TTL:
            continue
        activity = session.get(Activity, track.activity_id)
        if activity is None:
            continue
        before = _aware(existing.fetched_at) if existing is not None else None
        try:
            row = ensure_weather(session, activity, client, now=now)
        except Exception:
            logger.warning("weather enrichment failed for activity %s", track.activity_id, exc_info=True)
            session.rollback()
            stopped = "error"
            break
        wrote = row is not None and (before is None or _aware(row.fetched_at) != before)
        if not wrote:
            stopped = "provider_unavailable"
            break
        done += 1
        if row.status == "ok":
            ok += 1
    return {"processed": done, "ok": ok, "stopped": stopped}
