from __future__ import annotations

"""Open-Meteo historical weather client (session 20, docs/weather-endpoints.md).

One request fetches one 0.1-degree cell for one UTC day (24 hourly stamps) — the caller caches
that in `weather_cells`, so a given cell-day is only ever requested once it is final. The
provider sits behind this small class (`PROVIDER`, `fetch_day`) so the public build can swap in a
commercial plan or a different source without touching the matching code.

Fail-open like the Open Food Facts client: a rate-limit skip, an HTTP error or an unreadable body
returns None and never raises — weather is context, and a missing observation must never break a
sync.
"""

import logging
import time
from datetime import date, datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("catch.weather")

PROVIDER = "open-meteo"
BASE_URL = "https://archive-api.open-meteo.com"
# A generic client name. Deliberately NOT the OFF client's "name (email)" pattern: the athlete's
# email has no business in a request to a weather service.
USER_AGENT = "Catch/1.0 (self-hosted training log)"
ATTRIBUTION = (
    "Weather data by Open-Meteo.com (CC BY 4.0), based on ECMWF ERA5 / IFS reanalysis "
    "(contains modified Copernicus Climate Change Service information)."
)
ATTRIBUTION_URL = "https://open-meteo.com/"
LICENCE_NOTE = "Free API: non-commercial use only (see docs/weather-endpoints.md)."

HOURLY_VARS = (
    "temperature_2m", "relative_humidity_2m", "precipitation", "weather_code",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "pressure_msl",
)
# A day this many days old or older is treated as final: ERA5 lands ~5 days late, and the
# margin covers a late run. Anything newer is provisional and re-fetched after a TTL.
FINAL_AFTER_DAYS = 7

# Open-Meteo's free tier allows 600/min, 5,000/h, 10,000/day (and counts a 2-week request as
# several calls). A cell-day is one cheap call, so these are ceilings far below the real ones.
_MAX_PER_MINUTE = 30
_MAX_PER_DAY = 2000
_call_times: list[float] = []
_day_counter: dict[date, int] = {}


def _budget_ok() -> bool:
    now = time.monotonic()
    while _call_times and now - _call_times[0] > 60:
        _call_times.pop(0)
    if len(_call_times) >= _MAX_PER_MINUTE:
        return False
    today = datetime.now(timezone.utc).date()
    for old in [d for d in _day_counter if d != today]:
        del _day_counter[old]
    if _day_counter.get(today, 0) >= _MAX_PER_DAY:
        return False
    _call_times.append(now)
    _day_counter[today] = _day_counter.get(today, 0) + 1
    return True


def minute_budget_exhausted() -> bool:
    """True when the per-minute self-limit (not the daily one) is what's blocking requests, so a
    caller that wants to finish a backfill knows waiting a minute will help."""
    now = time.monotonic()
    return len([t for t in _call_times if now - t <= 60]) >= _MAX_PER_MINUTE


def is_final(day: date, today: Optional[date] = None) -> bool:
    today = today or datetime.now(timezone.utc).date()
    return (today - day).days >= FINAL_AFTER_DAYS


class OpenMeteoClient:
    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=15.0, headers={"User-Agent": USER_AGENT})

    def fetch_day(self, lat_e1: int, lon_e1: int, day: date) -> Optional[dict]:
        """{'hourly': {unix_ts: {var: value}}, 'grid_lat', 'grid_lon', 'elevation', 'complete'}.

        Coordinates arrive already rounded to 0.1 degree (tenths as ints) so the provider never
        sees a precise route. `complete` is True only for a final day with no gaps in any
        variable; a provisional or gappy day is stored but re-fetched later."""
        if not _budget_ok():
            logger.warning("weather request budget reached; skipping %s %s,%s", day, lat_e1, lon_e1)
            return None
        params = {
            "latitude": lat_e1 / 10.0,
            "longitude": lon_e1 / 10.0,
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "hourly": ",".join(HOURLY_VARS),
            "timezone": "GMT",  # cell-days are UTC days; never the host or activity timezone
            "timeformat": "unixtime",
            "wind_speed_unit": "kmh",
        }
        try:
            resp = self.http.get("/v1/archive", params=params)
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("weather fetch failed for %s", day, exc_info=True)
            return None
        return parse_response(body, day)


def parse_response(body: object, day: date) -> Optional[dict]:
    if not isinstance(body, dict) or body.get("error"):
        return None
    hourly = body.get("hourly")
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        return None
    times = hourly["time"]
    rows: dict[int, dict] = {}
    gaps = False
    for i, ts in enumerate(times):
        if not isinstance(ts, (int, float)):
            continue
        row = {}
        for var in HOURLY_VARS:
            series = hourly.get(var)
            v = series[i] if isinstance(series, list) and i < len(series) else None
            row[var] = v if isinstance(v, (int, float)) else None
            gaps = gaps or row[var] is None
        rows[int(ts)] = row
    if not rows:
        return None
    return {
        "hourly": rows,
        "grid_lat": body.get("latitude"),
        "grid_lon": body.get("longitude"),
        "elevation": body.get("elevation"),
        "complete": is_final(day) and not gaps and len(rows) == 24,
    }
