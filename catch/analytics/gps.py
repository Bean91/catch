from __future__ import annotations

"""GPS track filtering and metrics — pure functions, no I/O (session 20, docs/analytics.md §28).

Everything derived here comes from the device's own position fixes and timestamps and is
labelled `source: "gps_derived"` by the caller; values the provider (Garmin) reported itself are
kept separate and labelled `"provider"`, never blended into the derived numbers.
"""

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

from catch.analytics.downsample import lttb_indices

EARTH_RADIUS_M = 6371008.8  # IUGG mean radius; 1 degree of latitude = 111,194.9 m


@dataclass
class RawTrack:
    """Parallel arrays, one entry per FIT record. `t` is seconds from the file's first record
    (the same origin as ActivitySamples, so a chart's elapsed_s lines up across series)."""

    t: list[float]
    lat: list[Optional[float]]
    lon: list[Optional[float]]
    speed: list[Optional[float]] = field(default_factory=list)  # provider enhanced_speed, m/s
    dist: list[Optional[float]] = field(default_factory=list)  # provider cumulative metres
    alt: list[Optional[float]] = field(default_factory=list)
    hr: list[Optional[float]] = field(default_factory=list)


@dataclass
class FilteredTrack:
    t: list[float]
    lat: list[float]
    lon: list[float]
    segment: list[int]  # a new value starts after a gap or a re-anchored relocation
    speed: list[Optional[float]]  # provider speed carried through, same index as t
    alt: list[Optional[float]]
    hr: list[Optional[float]]
    cum_dist: list[float]  # GPS-derived cumulative metres over every in-segment pair
    pair_speed: list[float]  # derived m/s for the segment ending at i (0 at a segment start)
    pair_dist: list[float]  # metres of the pair ending at i (0 at a segment start)
    report: dict


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def speed_ceiling_mps(activity_type: Optional[str], sport_family: Optional[str], settings: dict) -> float:
    """Type keywords win over the coarse sport family so a Garmin 'walking'/'kayaking' row gets a
    realistic ceiling instead of the generic 'other' one."""
    t = (activity_type or "").lower()
    if "walk" in t or "hik" in t:
        return float(settings["speed_ceiling_walking_mps"])
    if "kayak" in t or "paddl" in t or "canoe" in t:
        return float(settings["speed_ceiling_paddling_mps"])
    key = {
        "rowing": "speed_ceiling_rowing_mps",
        "running": "speed_ceiling_running_mps",
        "cycling": "speed_ceiling_cycling_mps",
    }.get(sport_family or "", "speed_ceiling_other_mps")
    return float(settings[key])


def default_split_m(sport_family: Optional[str], settings: dict) -> float:
    key = {"rowing": "split_m_rowing", "running": "split_m_running", "cycling": "split_m_cycling"}.get(
        sport_family or "", "split_m_other"
    )
    return float(settings[key])


def _valid_coord(lat, lon) -> bool:
    if lat is None or lon is None:
        return False
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    if abs(lat) > 90 or abs(lon) > 180:
        return False
    # (0, 0) is "null island": a receiver that has no fix reporting zeros, never a real position.
    return not (lat == 0.0 and lon == 0.0)


def filter_track(raw: RawTrack, ceiling_mps: float, settings: dict) -> Optional[FilteredTrack]:
    """Returns None when fewer than two usable fixes survive (nothing to measure)."""
    n_in = len(raw.t)
    report = {
        "points_in": n_in,
        "dropped_no_fix": 0,
        "dropped_duplicate_time": 0,
        "dropped_out_of_order": 0,
        "dropped_jump": 0,
        "reanchored": 0,
        "gaps": 0,
        "gap_seconds": 0.0,
        "ceiling_mps": ceiling_mps,
    }

    def at(arr, i):
        return arr[i] if i < len(arr) else None

    # Pass 1: usable coordinates and strictly increasing time.
    cand: list[int] = []
    last_t: Optional[float] = None
    for i in range(n_in):
        if not _valid_coord(raw.lat[i], raw.lon[i]):
            report["dropped_no_fix"] += 1
            continue
        ti = raw.t[i]
        if last_t is not None:
            if ti == last_t:
                report["dropped_duplicate_time"] += 1
                continue
            if ti < last_t:
                report["dropped_out_of_order"] += 1
                continue
        cand.append(i)
        last_t = ti

    if len(cand) < 2:
        return None

    dts = [raw.t[b] - raw.t[a] for a, b in zip(cand, cand[1:])]
    median_dt = statistics.median(dts)
    gap_threshold = max(settings["gap_median_multiple"] * median_dt, float(settings["gap_min_s"]))
    report["gap_threshold_s"] = gap_threshold

    # Pass 2: impossible-jump rejection with re-anchoring, then gap segmentation.
    keep: list[int] = []
    seg_of: dict[int, int] = {}
    segment = 0
    pending: list[int] = []
    need = int(settings["reanchor_consecutive_points"])

    def implied(a: int, b: int) -> float:
        dt = raw.t[b] - raw.t[a]
        return haversine_m(raw.lat[a], raw.lon[a], raw.lat[b], raw.lon[b]) / dt if dt > 0 else math.inf

    for i in cand:
        if not keep:
            keep.append(i)
            seg_of[i] = segment
            continue
        prev = keep[-1]
        if raw.t[i] - raw.t[prev] > gap_threshold:
            segment += 1
            report["gaps"] += 1
            report["gap_seconds"] += raw.t[i] - raw.t[prev]
            pending = []
            keep.append(i)
            seg_of[i] = segment
            continue
        if implied(prev, i) <= ceiling_mps:
            pending = []
            keep.append(i)
            seg_of[i] = segment
            continue
        # Reject, but remember: a run of mutually consistent rejects is a real relocation.
        if pending and implied(pending[-1], i) > ceiling_mps:
            pending = []
        pending.append(i)
        if len(pending) >= need:
            segment += 1
            report["reanchored"] += 1
            for j in pending:
                keep.append(j)
                seg_of[j] = segment
            pending = []
        # else: counted as dropped below if never re-anchored

    kept = set(keep)
    report["dropped_jump"] = sum(1 for i in cand if i not in kept)

    if len(keep) < 2:
        return None

    t, lat, lon, seg, spd, alt, hr = [], [], [], [], [], [], []
    cum, pair_speed, pair_dist = [], [], []
    total = 0.0
    for idx, i in enumerate(keep):
        t.append(raw.t[i])
        lat.append(raw.lat[i])
        lon.append(raw.lon[i])
        seg.append(seg_of[i])
        spd.append(at(raw.speed, i))
        alt.append(at(raw.alt, i))
        hr.append(at(raw.hr, i))
        if idx > 0 and seg[idx] == seg[idx - 1]:
            p = keep[idx - 1]
            d = haversine_m(raw.lat[p], raw.lon[p], raw.lat[i], raw.lon[i])
            dt = raw.t[i] - raw.t[p]
            pair_speed.append(d / dt)
            pair_dist.append(d)
            # Every in-segment pair counts toward distance, slow drift included: on this account's
            # 29 real rows that matches Garmin's own distance to 0.15% (median), where dropping
            # sub-threshold pairs undercounted by 2.2%. Only *moving time* uses the threshold.
            total += d
        else:
            pair_speed.append(0.0)
            pair_dist.append(0.0)
        cum.append(total)

    return FilteredTrack(t=t, lat=lat, lon=lon, segment=seg, speed=spd, alt=alt, hr=hr,
                         cum_dist=cum, pair_speed=pair_speed, pair_dist=pair_dist, report=report)


def _median3(values: list[float]) -> list[float]:
    if len(values) < 3:
        return list(values)
    out = [values[0]]
    for i in range(1, len(values) - 1):
        out.append(statistics.median(values[i - 1 : i + 2]))
    out.append(values[-1])
    return out


def smoothed_speed(ft: FilteredTrack) -> list[float]:
    """Display speed: the derived pair speed with a 3-point median. A segment's first point has
    no incoming pair, so it borrows the next point's speed (never a made-up 0)."""
    raw = list(ft.pair_speed)
    for i in range(len(raw)):
        if i > 0 and ft.segment[i] != ft.segment[i - 1] and i + 1 < len(raw) and ft.segment[i + 1] == ft.segment[i]:
            raw[i] = raw[i + 1]
    if raw and ft.segment and len(raw) > 1 and ft.segment[0] == ft.segment[1]:
        raw[0] = raw[1]
    return _median3(raw)


def pace_seconds(speed_mps: Optional[float], per_m: float) -> Optional[float]:
    if speed_mps is None or speed_mps < 0.1:
        return None
    return per_m / speed_mps


def pace_for(speed_mps: Optional[float], sport_family: Optional[str]) -> dict:
    """{'unit', 'value'}: s/500 m rowing, s/km running, km/h otherwise. None value if too slow
    to be meaningful."""
    if sport_family == "rowing":
        return {"unit": "s_per_500m", "value": pace_seconds(speed_mps, 500.0)}
    if sport_family == "running":
        return {"unit": "s_per_km", "value": pace_seconds(speed_mps, 1000.0)}
    return {"unit": "km_per_h", "value": None if speed_mps is None else speed_mps * 3.6}


def peak_speed_mps(ft: FilteredTrack, window_s: float) -> Optional[float]:
    """Best chord speed (straight-line displacement / time) over any >= window_s stretch inside
    one segment. Chord, not path length: a one-fix GPS spike adds its out-and-back to the path
    but barely moves the endpoints, so it can't fake a sprint. Measured against this account's
    real rows the 3-point-median-of-pair-speeds alternative read up to 30% over Garmin's max."""
    best: Optional[float] = None
    n = len(ft.t)
    j = 0
    for i in range(n):
        if j < i:
            j = i
        while j < n and ft.segment[j] == ft.segment[i] and ft.t[j] - ft.t[i] < window_s:
            j += 1
        if j >= n or ft.segment[j] != ft.segment[i]:
            continue
        v = haversine_m(ft.lat[i], ft.lon[i], ft.lat[j], ft.lon[j]) / (ft.t[j] - ft.t[i])
        if best is None or v > best:
            best = v
    return best


def compute_metrics(ft: FilteredTrack, provider: Optional[dict], settings: dict) -> dict:
    """Each figure is {value, source, method}; provider figures sit alongside, never merged."""
    provider = provider or {}
    min_speed = float(settings["moving_speed_min_mps"])
    elapsed = ft.t[-1] - ft.t[0]
    moving = stopped = moving_dist = 0.0
    for i in range(1, len(ft.t)):
        if ft.segment[i] != ft.segment[i - 1]:
            continue
        dt = ft.t[i] - ft.t[i - 1]
        if ft.pair_speed[i] >= min_speed:
            moving += dt
            moving_dist += ft.pair_dist[i]
        else:
            stopped += dt
    distance = ft.cum_dist[-1]
    avg_speed = moving_dist / moving if moving > 0 else None
    avg_elapsed = distance / elapsed if elapsed > 0 else None
    peak = peak_speed_mps(ft, float(settings["peak_window_s"]))

    def derived(value, method):
        return {"value": value, "source": "gps_derived", "method": method}

    def prov(value):
        return {"value": value, "source": "provider", "method": "garmin"} if value is not None else None

    p_dist = provider.get("distance_m")
    delta_pct = None
    if p_dist and p_dist > 0:
        delta_pct = (distance - p_dist) / p_dist * 100.0

    return {
        "distance_m": derived(distance, "haversine sum over every in-segment pair; gaps excluded"),
        "moving_distance_m": derived(moving_dist, f"pairs at >= {min_speed} m/s"),
        "elapsed_s": derived(elapsed, "last accepted fix minus first"),
        "moving_s": derived(moving, f"sum of dt where pair speed >= {min_speed} m/s"),
        "stopped_s": derived(stopped, "in-segment dt where pair speed below moving threshold"),
        "gap_s": derived(ft.report["gap_seconds"], "time inside gaps, not counted anywhere"),
        "avg_speed_mps": derived(avg_speed, "moving distance / moving time"),
        "avg_speed_elapsed_mps": derived(
            avg_elapsed, "distance / elapsed time (the basis Garmin's own averageSpeed uses)"
        ),
        "peak_speed_mps": derived(peak, f"best chord speed over >= {settings['peak_window_s']} s"),
        "provider": {
            "distance_m": prov(p_dist),
            "moving_s": prov(provider.get("moving_s")),
            "elapsed_s": prov(provider.get("elapsed_s")),
            "avg_speed_mps": prov(provider.get("avg_speed_mps")),
            "max_speed_mps": prov(provider.get("max_speed_mps")),
        },
        "distance_delta_vs_provider_pct": delta_pct,
        "filter_report": ft.report,
    }


def compute_splits(ft: FilteredTrack, split_m: float, settings: dict) -> dict:
    """Splits over GPS cumulative distance. A boundary is the linearly interpolated instant the
    cumulative distance reaches k*split_m; elapsed wall time between boundaries is the split
    time (stops included — that's what a stopwatch would show). Splits touching a gap or a
    re-anchored relocation are flagged, and the final short remainder is `partial`."""
    out: list[dict] = []
    total = ft.cum_dist[-1]
    if split_m <= 0 or total <= 0:
        return {"split_m": split_m, "splits": [], "consistency": None}

    def time_at(target: float) -> float:
        for i in range(1, len(ft.cum_dist)):
            if ft.cum_dist[i] >= target:
                d0, d1 = ft.cum_dist[i - 1], ft.cum_dist[i]
                if d1 == d0:
                    return ft.t[i]
                return ft.t[i - 1] + (ft.t[i] - ft.t[i - 1]) * (target - d0) / (d1 - d0)
        return ft.t[-1]

    def idx_at(tt: float) -> int:
        for i, v in enumerate(ft.t):
            if v >= tt:
                return i
        return len(ft.t) - 1

    gap_times = [(ft.t[i - 1], ft.t[i]) for i in range(1, len(ft.t)) if ft.segment[i] != ft.segment[i - 1]]
    k = 0
    start_t = ft.t[0]
    # Distance already covered when the first fix arrives is 0 by construction.
    while True:
        target = (k + 1) * split_m
        full = target <= total + 1e-9
        end_dist = target if full else total
        start_dist = k * split_m
        # A remainder under a metre is float error at the end of the track, not a real partial split.
        if end_dist - start_dist < max(1.0, 0.002 * split_m):
            break
        end_t = time_at(end_dist) if full else ft.t[-1]
        dur = end_t - start_t
        if dur <= 0:
            break
        a, b = idx_at(start_t), idx_at(end_t)
        hrs = [h for h in ft.hr[a : b + 1] if h is not None]
        has_gap = any(g0 < end_t and g1 > start_t for g0, g1 in gap_times)
        dist = end_dist - start_dist
        speed = dist / dur
        out.append({
            "index": k + 1,
            "start_distance_m": start_dist,
            "distance_m": dist,
            "start_s": start_t,
            "time_s": dur,
            "speed_mps": speed,
            "avg_hr": (sum(hrs) / len(hrs)) if hrs else None,
            "partial": not full,
            "has_gap": has_gap,
        })
        if not full:
            break
        start_t = end_t
        k += 1

    full_clean = [s for s in out if not s["partial"] and not s["has_gap"]]
    consistency = None
    if len(full_clean) >= int(settings["pace_consistency_min_splits"]):
        speeds = [s["speed_mps"] for s in full_clean]
        times = [s["time_s"] for s in full_clean]
        mean_speed = statistics.fmean(speeds)
        consistency = {
            "cv_pct": statistics.pstdev(speeds) / mean_speed * 100.0 if mean_speed > 0 else None,
            "split_time_sd_s": statistics.pstdev(times),
            "n_splits": len(full_clean),
            "source": "gps_derived",
            "method": "population CV of full, gap-free split speeds",
        }
    return {"split_m": split_m, "splits": out, "consistency": consistency}


def cum_dist_at(ft: FilteredTrack, t: float) -> float:
    """GPS cumulative metres at elapsed time t, linearly interpolated between fixes and clamped
    to the track's ends. Time inside a gap is flat: no distance is invented across it."""
    if t <= ft.t[0]:
        return 0.0
    if t >= ft.t[-1]:
        return ft.cum_dist[-1]
    lo, hi = 0, len(ft.t) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ft.t[mid] <= t:
            lo = mid
        else:
            hi = mid
    if ft.segment[lo] != ft.segment[hi]:
        return ft.cum_dist[lo]
    f = (t - ft.t[lo]) / (ft.t[hi] - ft.t[lo])
    return ft.cum_dist[lo] + (ft.cum_dist[hi] - ft.cum_dist[lo]) * f


def lap_metrics(ft: FilteredTrack, laps: list[dict]) -> list[dict]:
    """GPS-derived distance/speed per FIT lap window, next to whatever the lap itself reported."""
    out = []
    for lap in laps:
        t0, dur = lap["offset_s"], lap["duration_s"]
        dist = cum_dist_at(ft, t0 + dur) - cum_dist_at(ft, t0)
        hrs = [h for t, h in zip(ft.t, ft.hr) if h is not None and t0 <= t <= t0 + dur]
        out.append({
            "offset_s": t0, "duration_s": dur,
            "gps_distance_m": dist,
            "gps_avg_speed_mps": dist / dur if dur > 0 else None,
            "gps_avg_hr": sum(hrs) / len(hrs) if hrs else None,
            "provider": {k: lap.get(k) for k in ("distance_m", "avg_speed_mps", "avg_hr", "max_hr", "avg_cadence")},
        })
    return out


def build_series(ft: FilteredTrack, points: int, sport_family: Optional[str]) -> list[dict]:
    """Downsample with LTTB on derived speed (same helper the HR chart uses), always keeping the
    first/last fix. Each point carries lat/lon so a map and charts share one array."""
    sm = smoothed_speed(ft)
    n = len(ft.t)
    idxs = lttb_indices(ft.t, sm, max(3, points)) if n > points else list(range(n))
    out = []
    for i in idxs:
        pace = pace_for(sm[i], sport_family)
        out.append({
            "elapsed_s": ft.t[i],
            "lat": ft.lat[i],
            "lon": ft.lon[i],
            "distance_m": ft.cum_dist[i],
            "speed_mps": sm[i],
            "provider_speed_mps": ft.speed[i],
            "pace_unit": pace["unit"],
            "pace": pace["value"],
            "hr": ft.hr[i],
            "elevation_m": ft.alt[i],
            "segment": ft.segment[i],
        })
    return out


def bounds(ft: FilteredTrack) -> dict:
    return {
        "min_lat": min(ft.lat), "max_lat": max(ft.lat),
        "min_lon": min(ft.lon), "max_lon": max(ft.lon),
    }


def detect_on_water(source: str, activity_type: Optional[str], has_track: bool) -> dict:
    """Distinguishes on-water from erg rowing from what the source itself says. The type string
    is authoritative; GPS presence is only the fallback basis for an unknown type."""
    from catch.analytics.classify import (
        CONCEPT2_ON_WATER_TYPES, GARMIN_ERG_TYPES, GARMIN_ON_WATER_TYPES,
    )

    if source == "garmin" and activity_type in GARMIN_ON_WATER_TYPES:
        return {"kind": "on_water", "basis": "garmin_type"}
    if source == "garmin" and activity_type in GARMIN_ERG_TYPES:
        return {"kind": "erg", "basis": "garmin_type"}
    if source == "concept2" and activity_type in CONCEPT2_ON_WATER_TYPES:
        return {"kind": "on_water", "basis": "concept2_type"}
    if source == "concept2":
        return {"kind": "erg", "basis": "concept2_type"}
    return {"kind": "unknown", "basis": "gps_track" if has_track else "none"}


def likely_rowing(cadence_spm: Optional[float], avg_speed_mps: Optional[float]) -> bool:
    """INFERENCE only — a GPS track with a stroke-rate-like cadence and a boat-like speed on an
    activity not typed as rowing. Never changes an activity's category."""
    if cadence_spm is None or avg_speed_mps is None:
        return False
    return 14 <= cadence_spm <= 40 and 2.0 <= avg_speed_mps <= 6.0
