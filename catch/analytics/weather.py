from __future__ import annotations

"""Matching hourly weather to an activity's time window — pure functions, no I/O (session 20,
docs/analytics.md §28.5, docs/weather-endpoints.md).

Everything is done on UTC instants (unix seconds). The provider's hourly stamps are UTC hour
starts (`timezone=GMT&timeformat=unixtime`), and an activity's window comes from the FIT's own
UTC timestamps — the host timezone and Garmin's startTimeLocal never enter into it.

Hour semantics differ per variable, and mixing them up shifts precipitation by an hour:
- `precipitation` is a *preceding-hour sum*: the value stamped T covers (T-1h, T].
- temperature, humidity, wind speed/direction/gusts and pressure are *instantaneous* at T, so
  they are interpolated linearly between stamps — and never across a missing stamp.
- `weather_code` is a point sample; the code nearest the window's midpoint is the headline and
  every distinct code in the bracketing stamps is listed.
Nothing is ever invented: a missing stamp lowers `coverage` and leaves the figure None.
"""

import math
from datetime import date, datetime, timezone
from typing import Optional

HOUR = 3600
POINT_VARS = ("temperature_2m", "relative_humidity_2m", "wind_speed_10m", "wind_gusts_10m", "pressure_msl")
ALL_VARS = POINT_VARS + ("wind_direction_10m", "precipitation", "weather_code")

# Standard WMO present-weather codes as Open-Meteo reports them.
WMO_TEXT = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def to_utc_ts(dt: datetime) -> float:
    """Unix seconds. A naive datetime is read as UTC — that is how this app stores every
    instant (SQLite hands datetimes back without tzinfo)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def floor_hour(ts: float) -> int:
    return int(ts // HOUR * HOUR)


def ceil_hour(ts: float) -> int:
    return int(-(-ts // HOUR) * HOUR)


def utc_dates_needed(start_ts: float, end_ts: float) -> list[date]:
    """UTC days whose hourly stamps the window needs: from the stamp at/below the start to the
    one at/above the end (precipitation stamped at 00:00 belongs to the previous day's hour, so a
    window ending at 23:40 needs the next day's 00:00 stamp)."""
    d0 = datetime.fromtimestamp(floor_hour(start_ts), timezone.utc).date()
    d1 = datetime.fromtimestamp(ceil_hour(end_ts), timezone.utc).date()
    out, d = [], d0
    while d <= d1:
        out.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    return out


def compass_label(deg: Optional[float]) -> Optional[str]:
    if deg is None:
        return None
    return _COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def _lerp(a: float, b: float, f: float) -> float:
    return a + (b - a) * f


def _lerp_deg(a: float, b: float, f: float) -> float:
    """Along the shortest arc, so 350 -> 10 passes through 0, not 180."""
    diff = (b - a + 180) % 360 - 180
    return (a + diff * f) % 360


def circular_mean_deg(angles: list[float], weights: Optional[list[float]] = None) -> Optional[float]:
    if not angles:
        return None
    w = weights or [1.0] * len(angles)
    x = sum(wi * math.cos(math.radians(a)) for a, wi in zip(angles, w))
    y = sum(wi * math.sin(math.radians(a)) for a, wi in zip(angles, w))
    if math.hypot(x, y) < 1e-9:
        return None  # opposite directions cancel: there is no meaningful mean
    return math.degrees(math.atan2(y, x)) % 360


def _point_stat(hourly: dict, var: str, start: float, end: float, circular: bool = False):
    """Time-weighted mean over [start, end] of the piecewise-linear series, using only segments
    whose two bounding stamps both exist. Returns (mean, min, max, covered_seconds)."""
    stamps = sorted(hourly)
    acc = covered = 0.0
    lo = hi = None
    angles: list[float] = []
    weights: list[float] = []
    for t0, t1 in zip(stamps, stamps[1:]):
        a, b = max(start, t0), min(end, t1)
        if b <= a:
            continue
        v0, v1 = hourly[t0].get(var), hourly[t1].get(var)
        if v0 is None or v1 is None:
            continue
        span = t1 - t0
        lerp = _lerp_deg if circular else _lerp
        va, vb = lerp(v0, v1, (a - t0) / span), lerp(v0, v1, (b - t0) / span)
        if circular:
            n = 4
            for k in range(n):
                fa = (a - t0) / span + (b - a) / span * (k + 0.5) / n
                angles.append(_lerp_deg(v0, v1, fa))
                weights.append((b - a) / n)
        else:
            acc += (va + vb) / 2 * (b - a)
        covered += b - a
        for v in (va, vb):
            lo = v if lo is None else min(lo, v)
            hi = v if hi is None else max(hi, v)
    if covered <= 0:
        return None, None, None, 0.0
    mean = circular_mean_deg(angles, weights) if circular else acc / covered
    return mean, lo, hi, covered


def _precip_total(hourly: dict, start: float, end: float):
    total = covered = 0.0
    for t, row in hourly.items():
        ov = max(0.0, min(end, t) - max(start, t - HOUR))
        if ov <= 0:
            continue
        v = row.get("precipitation")
        if v is None:
            continue
        total += v * ov / HOUR
        covered += ov
    return (total if covered > 0 else None), covered


def summarize_window(hourly: dict[int, dict], start_ts: float, end_ts: float) -> dict:
    """`hourly` maps UTC hour-start unix seconds -> {variable: value-or-None}. Returns the
    observed summary with a per-variable coverage figure; every number is provider data
    interpolated in time, not a measurement at the water."""
    duration = end_ts - start_ts
    if duration <= 0:
        raise ValueError("window must have positive duration")

    temp, tmin, tmax, c_temp = _point_stat(hourly, "temperature_2m", start_ts, end_ts)
    hum, _, _, c_hum = _point_stat(hourly, "relative_humidity_2m", start_ts, end_ts)
    wind, _, _, c_wind = _point_stat(hourly, "wind_speed_10m", start_ts, end_ts)
    _, _, gust_max, c_gust = _point_stat(hourly, "wind_gusts_10m", start_ts, end_ts)
    wdir, _, _, c_dir = _point_stat(hourly, "wind_direction_10m", start_ts, end_ts, circular=True)
    pres, _, _, c_pres = _point_stat(hourly, "pressure_msl", start_ts, end_ts)
    precip, c_precip = _precip_total(hourly, start_ts, end_ts)

    lo, hi = floor_hour(start_ts), ceil_hour(end_ts)
    bracket = [t for t in sorted(hourly) if lo <= t <= hi]
    mid = (start_ts + end_ts) / 2
    coded = [(abs(t - mid), t) for t in bracket if hourly[t].get("weather_code") is not None]
    primary = None
    if coded:
        primary = int(hourly[min(coded)[1]]["weather_code"])
    codes = sorted({int(hourly[t]["weather_code"]) for t in bracket if hourly[t].get("weather_code") is not None})

    frac = lambda c: round(min(1.0, c / duration), 4)  # noqa: E731
    core = [frac(c_temp), frac(c_wind), frac(c_precip)]
    coverage = sum(core) / len(core)

    return {
        "window_start": datetime.fromtimestamp(start_ts, timezone.utc).isoformat(),
        "window_end": datetime.fromtimestamp(end_ts, timezone.utc).isoformat(),
        "duration_s": duration,
        "temperature_c": {"avg": temp, "min": tmin, "max": tmax},
        "humidity_pct": hum,
        "wind": {
            "speed_kmh": wind,
            "speed_mps": None if wind is None else wind / 3.6,
            "gust_max_kmh": gust_max,
            "direction_from_deg": wdir,
            "direction_from_label": compass_label(wdir),
        },
        "pressure_hpa": pres,
        "precipitation_mm": precip,
        "condition": {
            "code": primary,
            "text": WMO_TEXT.get(primary) if primary is not None else None,
            "codes_in_window": [{"code": c, "text": WMO_TEXT.get(c, f"WMO {c}")} for c in codes],
        },
        "coverage": round(coverage, 4),
        "core_coverage_min": min(core),
        "variable_coverage": {
            "temperature": frac(c_temp), "humidity": frac(c_hum), "wind_speed": frac(c_wind),
            "wind_gusts": frac(c_gust), "wind_direction": frac(c_dir), "pressure": frac(c_pres),
            "precipitation": frac(c_precip),
        },
        "hours": [
            {"ts": t, "time": datetime.fromtimestamp(t, timezone.utc).isoformat(),
             **{v: hourly[t].get(v) for v in ALL_VARS}}
            for t in bracket
        ],
    }


def status_for(summary: dict, provisional: bool) -> str:
    """ok | partial | unavailable. 'unavailable' = nothing at all for the window. 'partial' = the
    weakest of the core variables (temperature, wind speed, precipitation) covers under half the
    window, or the day is still provisional (not final reanalysis) — the figures are shown,
    flagged, and re-checked later. Judged on the weakest variable, not the average, so a window
    with no temperature at all can never read as complete."""
    if summary["coverage"] <= 0:
        return "unavailable"
    if summary["core_coverage_min"] < 0.5 or provisional:
        return "partial"
    return "ok"
