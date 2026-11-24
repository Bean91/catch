"""Session 36 follow-up: one rowing-erg recording's strokes reduced to what the Performance Lab compares. Pure, no I/O (the cache
lives in catch/sync/stroke_summary.py).

  * Rate bands: per 2 spm band, how many strokes and the sum of their splits — the same filters the per-stroke query used
    (rate 14–50 spm, split 1:00–5:00 /500 m), so a cached summary and a fresh count agree. Rates are rounded half up before
    banding, as SQL's ROUND does.
  * Best power curve: the highest time-weighted average power over each standard duration. A stroke's watts hold from the
    previous stroke to it (the PM5 reports a stroke when it finishes). A window never spans a rest between intervals or a pause
    longer than `MAX_GAP_S`, and a duration is only reported when one continuous run is at least that long. The watts are
    Concept2's own pace-to-watts formula applied to each stroke's pace (catch/analytics/erg_math.py) — derived, not measured — so
    the curve exists only for the rowing erg.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

from catch.analytics import performance_lab as lab

SUMMARY_VERSION = 1
CURVE_DURATIONS_S = (10, 30, 60, 120, 300, 600, 1200, 1800, 3600)
MAX_GAP_S = 10.0
PACE_RANGE = (60.0, 300.0)


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def rate_bands(strokes: Iterable[dict]) -> dict[str, list[float]]:
    """`{band: [strokes, pace_sum]}` with the band as a string key (it is stored as JSON)."""
    out: dict[str, list[float]] = {}
    for s in strokes:
        rate, pace = s.get("stroke_rate"), s.get("pace_500m")
        if rate is None or pace is None:
            continue
        if not (lab.RATE_RANGE[0] <= rate <= lab.RATE_RANGE[1]) or not (PACE_RANGE[0] <= pace <= PACE_RANGE[1]):
            continue
        key = str(lab.rate_band(float(_round_half_up(rate))))
        cell = out.setdefault(key, [0, 0.0])
        cell[0] += 1
        cell[1] += float(pace)
    return out


def _runs(strokes: list[dict]) -> list[tuple[list[float], list[float]]]:
    """Continuous runs as (times, watts): split at an interval change, a pause longer than `MAX_GAP_S`, a clock that goes
    backwards, or a stroke with no watts. Times are seconds within the run's interval."""
    runs: list[tuple[list[float], list[float]]] = []
    times: list[float] = []
    watts: list[float] = []
    prev_interval: object = object()
    for s in strokes:
        t, w, interval = s.get("t"), s.get("watts"), s.get("interval_index")
        broken = (
            t is None or w is None or interval != prev_interval or not times
            or t - times[-1] > MAX_GAP_S or t <= times[-1]
        )
        if broken:
            if len(times) >= 2:
                runs.append((times, watts))
            times, watts = [], []
        if t is not None and w is not None:
            times.append(float(t))
            watts.append(float(w))
        prev_interval = interval
    if len(times) >= 2:
        runs.append((times, watts))
    return runs


def _best_average(times: list[float], watts: list[float], duration: float) -> Optional[float]:
    """Highest average of the step function (watts[i] on (times[i-1], times[i]]) over any window of `duration` seconds. With a
    step function, the best window starts or ends on a stroke, so only those windows are checked."""
    n = len(times)
    if times[-1] - times[0] < duration:
        return None
    cum = [0.0] * n
    for i in range(1, n):
        cum[i] = cum[i - 1] + watts[i] * (times[i] - times[i - 1])

    def energy(x: float, k: int) -> float:
        # energy from times[0] to x, where times[k] <= x <= times[k + 1]
        if k >= n - 1:
            return cum[-1]
        return cum[k] + watts[k + 1] * (x - times[k])

    best = -1.0
    k = 0
    for i in range(n):  # windows starting at a stroke
        end = times[i] + duration
        if end > times[-1] + 1e-9:
            break
        while k + 1 < n and times[k + 1] <= end:
            k += 1
        best = max(best, (energy(end, k) - cum[i]) / duration)
    k = 0
    for j in range(n):  # windows ending at a stroke
        start = times[j] - duration
        if start < times[0] - 1e-9:
            continue
        while k + 1 < n and times[k + 1] <= start:
            k += 1
        best = max(best, (cum[j] - energy(start, k)) / duration)
    return best if best >= 0 else None


def power_curve(strokes: list[dict]) -> dict[str, float]:
    """`{duration_s: best average watts}` (string keys, one decimal), only for durations some continuous run covers."""
    runs = _runs(strokes)
    out: dict[str, float] = {}
    for d in CURVE_DURATIONS_S:
        best = None
        for times, watts in runs:
            v = _best_average(times, watts, float(d))
            if v is not None and (best is None or v > best):
                best = v
        if best is not None:
            out[str(d)] = round(best, 1)
    return out


def summarize(strokes: list[dict], *, watts_derived: bool) -> dict:
    """The cached summary of one recording. `strokes` in recording order (seq), with t/interval_index/pace_500m/watts/
    stroke_rate."""
    return {
        "v": SUMMARY_VERSION,
        "n": len(strokes),
        "rate_bands": rate_bands(strokes),
        "power_curve": power_curve(strokes),
        "watts_derived": watts_derived,
    }


def best_curve(entries: list[dict]) -> list[dict]:
    """`entries`: `{curve, date, ref}` per recording. Per standard duration, the best average power and where it came from."""
    out = []
    for d in CURVE_DURATIONS_S:
        best = None
        for e in entries:
            v = (e.get("curve") or {}).get(str(d))
            if v is not None and (best is None or v > best["watts"]):
                best = {"watts": v, "date": e["date"], "ref": e["ref"]}
        out.append({"duration_s": d, "best": best})
    return out


def curve_halves(entries: list[dict], split) -> list[dict]:
    """The curve for the whole range and for each half, side by side; a half with no recording long enough is None."""
    earlier = best_curve([e for e in entries if e["date"] < split])
    recent = best_curve([e for e in entries if e["date"] >= split])
    whole = best_curve(entries)
    return [
        {"duration_s": w["duration_s"], "best": w["best"], "earlier": e["best"], "recent": r["best"]}
        for w, e, r in zip(whole, earlier, recent)
    ]
