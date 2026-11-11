from __future__ import annotations

"""Route signatures and alignment — pure functions, no I/O (session 20, docs/analytics.md §28.4).

A signature is a fixed number of points resampled by distance along the GPS path, so two rows of
the same course agree regardless of pace or recording rate. Two tracks "align" only when they
start and end together, are the same length, and each covers the other — and direction is
recorded, so an out-and-back and its reverse are never merged silently."""

import math
from typing import Optional

from catch.analytics.gps import EARTH_RADIUS_M, FilteredTrack, haversine_m

SIGNATURE_POINTS = 64


def signature(ft: FilteredTrack, n: int = SIGNATURE_POINTS) -> list[list[float]]:
    """n points evenly spaced by GPS cumulative distance. Empty if the track has no extent."""
    total = ft.cum_dist[-1]
    if total <= 0 or len(ft.t) < 2:
        return []
    out: list[list[float]] = []
    j = 1
    for k in range(n):
        target = total * k / (n - 1)
        while j < len(ft.cum_dist) - 1 and ft.cum_dist[j] < target:
            j += 1
        d0, d1 = ft.cum_dist[j - 1], ft.cum_dist[j]
        f = 0.0 if d1 == d0 else min(1.0, max(0.0, (target - d0) / (d1 - d0)))
        out.append([
            round(ft.lat[j - 1] + (ft.lat[j] - ft.lat[j - 1]) * f, 6),
            round(ft.lon[j - 1] + (ft.lon[j] - ft.lon[j - 1]) * f, 6),
        ])
    return out


def _project(points: list[list[float]], lat0: float) -> list[tuple[float, float]]:
    k = math.cos(math.radians(lat0))
    return [
        (math.radians(lon) * EARTH_RADIUS_M * k, math.radians(lat) * EARTH_RADIUS_M)
        for lat, lon in points
    ]


def _dist_to_polyline(p: tuple[float, float], line: list[tuple[float, float]]) -> float:
    best = math.inf
    px, py = p
    for (ax, ay), (bx, by) in zip(line, line[1:]):
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if d < best:
            best = d
    return best


def _coverage(a: list[tuple[float, float]], b: list[tuple[float, float]], within_m: float) -> float:
    return sum(1 for p in a if _dist_to_polyline(p, b) <= within_m) / len(a)


def path_length_m(sig: list[list[float]]) -> float:
    return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(sig, sig[1:]))


def match(sig_a: list[list[float]], sig_b: list[list[float]], settings: dict) -> dict:
    """{'aligned', 'direction', 'coverage', 'start_m', 'end_m', 'length_ratio_delta'}."""
    result = {"aligned": False, "direction": None, "coverage": 0.0, "start_m": None,
              "end_m": None, "length_ratio_delta": None}
    if len(sig_a) < 2 or len(sig_b) < 2 or len(sig_a) != len(sig_b):
        return result
    la, lb = path_length_m(sig_a), path_length_m(sig_b)
    if max(la, lb) <= 0:
        return result
    result["length_ratio_delta"] = abs(la - lb) / max(la, lb)

    n = len(sig_a)
    d_same = sum(haversine_m(*sig_a[i], *sig_b[i]) for i in range(n)) / n
    d_rev = sum(haversine_m(*sig_a[i], *sig_b[n - 1 - i]) for i in range(n)) / n
    result["direction"] = "same" if d_same <= d_rev else "reversed"
    b = sig_b if result["direction"] == "same" else sig_b[::-1]
    result["start_m"] = haversine_m(*sig_a[0], *b[0])
    result["end_m"] = haversine_m(*sig_a[-1], *b[-1])

    lat0 = sum(p[0] for p in sig_a) / n
    pa, pb = _project(sig_a, lat0), _project(b, lat0)
    within = float(settings["route_coverage_dist_m"])
    result["coverage"] = min(_coverage(pa, pb, within), _coverage(pb, pa, within))

    result["aligned"] = (
        result["direction"] == "same"
        and result["length_ratio_delta"] <= float(settings["route_length_ratio_tol"])
        and result["start_m"] <= float(settings["route_endpoint_tol_m"])
        and result["end_m"] <= float(settings["route_endpoint_tol_m"])
        and result["coverage"] >= float(settings["route_coverage_min"])
    )
    return result


def eligible(gap_fraction: Optional[float], settings: dict) -> bool:
    """A track riddled with gaps can't be compared honestly to anything."""
    return gap_fraction is not None and gap_fraction <= float(settings["route_max_gap_fraction"])


# --- history ---------------------------------------------------------------------------------

import statistics  # noqa: E402

CAVEATS = [
    "Times are moving time on the same recorded course. They are not wind-, current- or "
    "water-corrected, and a session's structure (steady row, intervals, warm-up) is included.",
    "Weather beside each session is provider data for the area, shown for context only; "
    "it is not used to adjust any figure here.",
]
WEATHER_NOTE = (
    "Observed provider data, not a correction. Wind direction relative to the course "
    "is not factored in, so this cannot say whether the wind helped or hurt."
)


def _quartiles(values: list[float]) -> dict:
    s = sorted(values)
    if len(s) == 1:
        return {"min": s[0], "p25": s[0], "median": s[0], "p75": s[0], "max": s[0]}
    q = statistics.quantiles(s, n=4, method="inclusive")
    return {"min": s[0], "p25": q[0], "median": q[1], "p75": q[2], "max": s[-1]}


def _histogram(values: list[float], bins: int = 5) -> list[dict]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [{"from": lo, "to": hi, "count": len(values)}]
    width = (hi - lo) / bins
    out = [{"from": lo + i * width, "to": lo + (i + 1) * width, "count": 0} for i in range(bins)]
    for v in values:
        out[min(bins - 1, int((v - lo) / width))]["count"] += 1
    return out


def history_stats(sessions: list[dict]) -> dict:
    """Pure. Each session: {date, canonical_id, avg_speed_mps, moving_s, elapsed_s, distance_m,
    avg_hr, weather}. Ranks by moving average speed; every figure is GPS-derived and says so."""
    usable = sorted((s for s in sessions if s.get("avg_speed_mps")), key=lambda s: s["date"])
    base = {
        "n_sessions": len(usable), "best": None, "typical_avg_speed_mps": None, "recent": None,
        "recent_vs_typical_pct": None, "speed_distribution": None, "hr": None,
        "weather_differences": [], "caveats": CAVEATS, "source": "gps_derived",
    }
    if not usable:
        return base
    speeds = [s["avg_speed_mps"] for s in usable]
    best = max(usable, key=lambda s: s["avg_speed_mps"])
    typical = statistics.median(speeds)
    recent = usable[-1]
    hrs = [s["avg_hr"] for s in usable if s.get("avg_hr")]
    out = {
        **base,
        "best": best,
        "typical_avg_speed_mps": typical,
        "recent": recent,
        "recent_vs_typical_pct": (recent["avg_speed_mps"] - typical) / typical * 100.0 if len(usable) > 1 else None,
        "speed_distribution": {**_quartiles(speeds), "n": len(speeds), "histogram": _histogram(speeds),
                               "basis": "each session's average moving speed"},
        "hr": {"n": len(hrs), "mean": statistics.fmean(hrs), "min": min(hrs), "max": max(hrs)} if hrs else None,
    }
    others = [s for s in usable if s is not best and s.get("weather")]
    if best.get("weather") and others:
        for key, label in (("temperature_avg_c", "temperature (C)"), ("wind_speed_kmh", "wind speed (km/h)"),
                           ("precipitation_mm", "precipitation (mm)")):
            vals = [o["weather"][key] for o in others if o["weather"].get(key) is not None]
            b = best["weather"].get(key)
            if b is not None and vals:
                med = statistics.median(vals)
                out["weather_differences"].append({
                    "metric": label, "best_session": b, "other_sessions_median": med,
                    "difference": b - med, "kind": "observed_difference", "note": WEATHER_NOTE,
                })
    return out
