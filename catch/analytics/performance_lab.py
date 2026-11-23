"""Session 36: the Performance Lab's comparisons over time. Pure, no I/O (the DB half is catch/sync/performance_lab.py).

Every comparison here splits the chosen date range into an earlier and a recent half and puts the two side by side, only where
both halves have enough data. Nothing is extrapolated, no band is called good or bad, and a cell without enough data is None
with the count it had — never a number made from too little.

  * Heart rate at comparable workloads: continuous rowing-erg sessions grouped by their average power (20 W bands). The median
    heart rate of each half needs at least `MIN_SESSIONS` sessions in that band. Lower heart rate at the same power is the
    conventional sign of improved aerobic fitness, but heat, caffeine, fatigue and a different HR sensor move it too — said on
    screen, not here.
  * Split at comparable stroke rates: every stroke in the range, grouped by rate (2 spm bands). Each half's figure is the mean of
    the per-stroke splits (stroke-weighted), needing `MIN_STROKES` strokes from at least `MIN_SESSIONS` sessions.
  * Progression: each standard distance/time's efforts in date order (pace and power), for a chart — no smoothing, no trend line.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Optional

POWER_BAND_W = 20
RATE_BAND_SPM = 2
MIN_SESSIONS = 2
MIN_STROKES = 60
RATE_RANGE = (14, 50)


def midpoint(start: date, end: date) -> date:
    return start + timedelta(days=(end - start).days // 2)


def power_band(watts: float) -> int:
    return int(watts // POWER_BAND_W) * POWER_BAND_W


def rate_band(rate: float) -> int:
    return int(rate // RATE_BAND_SPM) * RATE_BAND_SPM


def _side_hr(rows: list[dict]) -> dict:
    hrs = [r["avg_hr"] for r in rows]
    return {
        "sessions": len(rows),
        "median_hr": statistics.median(hrs) if len(rows) >= MIN_SESSIONS else None,
        "median_watts": statistics.median([r["avg_watts"] for r in rows]) if len(rows) >= MIN_SESSIONS else None,
        "refs": [r["ref"] for r in rows][:10],
    }


def hr_at_workload(sessions: list[dict], split: date) -> list[dict]:
    """`sessions`: `{date, avg_watts, avg_hr, ref}`. One row per 20 W band that has any session, highest power first."""
    bands: dict[int, dict[str, list[dict]]] = {}
    for s in sessions:
        if not s.get("avg_watts") or not s.get("avg_hr"):
            continue
        side = "recent" if s["date"] >= split else "earlier"
        bands.setdefault(power_band(s["avg_watts"]), {"earlier": [], "recent": []})[side].append(s)
    out = []
    for band in sorted(bands, reverse=True):
        e, r = _side_hr(bands[band]["earlier"]), _side_hr(bands[band]["recent"])
        change = (r["median_hr"] - e["median_hr"]) if e["median_hr"] is not None and r["median_hr"] is not None else None
        out.append({"band_w": [band, band + POWER_BAND_W], "earlier": e, "recent": r, "hr_change_bpm": change})
    return out


def split_by_rate(rows: list[dict], split: date) -> list[dict]:
    """`rows`: per session and rate band, `{date, band, strokes, pace_sum}` (pace_sum = sum of per-stroke splits in s/500 m)."""
    agg: dict[int, dict[str, dict]] = {}
    for r in rows:
        side = "recent" if r["date"] >= split else "earlier"
        cell = agg.setdefault(r["band"], {"earlier": {"strokes": 0, "pace_sum": 0.0, "sessions": set()}, "recent": {"strokes": 0, "pace_sum": 0.0, "sessions": set()}})[side]
        cell["strokes"] += r["strokes"]
        cell["pace_sum"] += r["pace_sum"]
        cell["sessions"].add(r["session"])

    def finish(cell: dict) -> dict:
        ok = cell["strokes"] >= MIN_STROKES and len(cell["sessions"]) >= MIN_SESSIONS
        return {"strokes": cell["strokes"], "sessions": len(cell["sessions"]), "split_s": (cell["pace_sum"] / cell["strokes"]) if ok else None}

    out = []
    for band in sorted(agg):
        e, r = finish(agg[band]["earlier"]), finish(agg[band]["recent"])
        change = (r["split_s"] - e["split_s"]) if e["split_s"] is not None and r["split_s"] is not None else None
        out.append({"band_spm": [band, band + RATE_BAND_SPM], "earlier": e, "recent": r, "split_change_s": change})
    return out


def progression(candidates: list[dict], distances_m: tuple, durations_s: dict, split_m: float) -> list[dict]:
    """For each standard distance/time with at least one effort: every effort in date order, with its pace and power and whether
    it set a new best at that moment (a record-history marker, not a trend)."""
    out = []
    for target in distances_m:
        tol = max(25.0, target * 0.02)
        pts = sorted((c for c in candidates if abs(c["distance_m"] - target) <= tol), key=lambda c: (c["date"], c["duration_s"]))
        out.append(_series(f"{target}m", pts, split_m, lambda a, b: a["duration_s"] < b["duration_s"]))
    for target, key in durations_s.items():
        pts = sorted((c for c in candidates if abs(c["duration_s"] - target) <= 30.0), key=lambda c: (c["date"], -c["distance_m"]))
        out.append(_series(key, pts, split_m, lambda a, b: a["distance_m"] > b["distance_m"]))
    return [s for s in out if s["points"]]


def _series(key: str, pts: list[dict], split_m: float, better) -> dict:
    best: Optional[dict] = None
    points = []
    for c in pts:
        is_best = best is None or better(c, best)
        if is_best:
            best = c
        points.append({
            "date": c["date"], "distance_m": c["distance_m"], "duration_s": c["duration_s"],
            "pace_s": c["duration_s"] / c["distance_m"] * split_m if c["distance_m"] else None,
            "avg_watts": c.get("avg_watts"), "watts_basis": c.get("watts_basis"), "label": c["label"],
            "new_best": is_best, "ref": c.get("ref"),
        })
    return {"key": key, "points": points}
