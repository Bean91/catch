"""Session 36 follow-up: lining up a PM5's strokes with another device's recording (a watch) on workout detail. Pure, no I/O (the
DB half is catch/sync/recording_offset.py).

Two devices' clocks are never assumed to agree, so the charts share a cursor across them only at an offset the athlete has
confirmed. This module can *propose* one: it slides the erg's series along the watch's and keeps the shift where the two agree best —
heart rate against heart rate when both have it, else the erg's stroke rate against the watch's cadence. A proposal is offered only
when the agreement is strong (Pearson r ≥ `MIN_R` over at least `MIN_OVERLAP_S` of shared seconds), both series actually vary, and
the best shift stands clear of every shift more than `PEAK_EXCLUSION_S` away (by `MIN_MARGIN`). Anything less: no proposal, and
the athlete can still set the offset by hand.

Time on the erg side is wall time since the PM5 started, rests included: `wall_times` adds each finished interval's time and its
rest. When an interval session's rest isn't known, wall time isn't either, and nothing is proposed or accepted.

The offset is the watch-chart second at which the erg recording's second 0 falls: watch time = erg wall time + offset.
"""

from __future__ import annotations

import math
from typing import Optional

MAX_SHIFT_S = 900
COARSE_STEP_S = 5
MIN_OVERLAP_S = 180
MIN_R = 0.85
MIN_MARGIN = 0.1
PEAK_EXCLUSION_S = 30
MIN_SPREAD = 1.5


def wall_times(strokes: list[dict], interval_defs: list[dict]) -> Optional[list[float]]:
    """Each stroke's seconds since the PM5 started, rest included. `strokes` in order with `t` (seconds within the interval) and
    `interval_index`; `interval_defs` Concept2's own `workout.intervals` (time and rest_time in tenths). None when there is more
    than one interval and a rest or an interval's time isn't reported."""
    indices = sorted({s.get("interval_index") or 0 for s in strokes})
    if len(indices) <= 1 and not interval_defs:
        return [float(s["t"]) for s in strokes]
    starts: dict[int, float] = {}
    clock = 0.0
    for i in range(max(indices) + 1 if indices else 0):
        starts[i] = clock
        if i >= len(interval_defs):
            if i < max(indices):
                return None
            break
        d = interval_defs[i]
        time_t, rest_t = d.get("time"), d.get("rest_time")
        if time_t is None or (rest_t is None and i < max(indices)):
            return None
        clock += time_t / 10.0 + (rest_t or 0) / 10.0
    return [starts[s.get("interval_index") or 0] + float(s["t"]) for s in strokes]


def resample(times: list[float], values: list[Optional[float]], length: int, *, hold_s: float = 5.0) -> list[Optional[float]]:
    """A 1 Hz series of `length` seconds: each second takes the latest value at or before it, for at most `hold_s` seconds."""
    out: list[Optional[float]] = [None] * max(0, length)
    j = -1
    for sec in range(len(out)):
        while j + 1 < len(times) and times[j + 1] <= sec:
            j += 1
        if j >= 0 and values[j] is not None and sec - times[j] <= hold_s:
            out[sec] = values[j]
    return out


def _bucket(series: list[Optional[float]], step: int) -> list[Optional[float]]:
    out = []
    for i in range(0, len(series), step):
        chunk = [v for v in series[i : i + step] if v is not None]
        out.append(sum(chunk) / len(chunk) if chunk else None)
    return out


def _corr(a: list[Optional[float]], b: list[Optional[float]], shift: int, min_pairs: int) -> Optional[float]:
    """Pearson r of a[k + shift] against b[k] over the seconds both define, or None with too little overlap or no spread."""
    xs, ys = [], []
    for k, y in enumerate(b):
        i = k + shift
        if 0 <= i < len(a) and y is not None and a[i] is not None:
            xs.append(a[i])
            ys.append(y)
    n = len(xs)
    if n < min_pairs:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def _spread(series: list[Optional[float]]) -> float:
    v = [x for x in series if x is not None]
    if len(v) < 2:
        return 0.0
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))


def suggest_offset(watch: list[Optional[float]], erg: list[Optional[float]], *, centre_s: int = 0, signal: str) -> dict:
    """`watch` and `erg` are 1 Hz series from each recording's own start. Returns `{offset_s, r, overlap_s, signal}` or
    `{offset_s: None, reason}`. Shifts are searched within `MAX_SHIFT_S` of `centre_s` (the two clocks' own difference)."""
    if _spread(watch) < MIN_SPREAD or _spread(erg) < MIN_SPREAD:
        return {"offset_s": None, "signal": signal, "reason": "One of the two recordings barely changes, so there is nothing to line up."}
    cw, ce = _bucket(watch, COARSE_STEP_S), _bucket(erg, COARSE_STEP_S)
    lo, hi = (centre_s - MAX_SHIFT_S) // COARSE_STEP_S, (centre_s + MAX_SHIFT_S) // COARSE_STEP_S
    coarse = {}
    for shift in range(lo, hi + 1):
        r = _corr(cw, ce, shift, MIN_OVERLAP_S // COARSE_STEP_S)
        if r is not None:
            coarse[shift * COARSE_STEP_S] = r
    if not coarse:
        return {"offset_s": None, "signal": signal, "reason": "The recordings don't overlap for long enough at any offset."}
    best_coarse = max(coarse, key=coarse.get)
    fine = {}
    for shift in range(best_coarse - COARSE_STEP_S, best_coarse + COARSE_STEP_S + 1):
        r = _corr(watch, erg, shift, MIN_OVERLAP_S)
        if r is not None:
            fine[shift] = r
    if not fine:
        return {"offset_s": None, "signal": signal, "reason": "The recordings don't overlap for long enough at any offset."}
    best = max(fine, key=fine.get)
    r = fine[best]
    rival = max((v for s, v in coarse.items() if abs(s - best) > PEAK_EXCLUSION_S), default=-1.0)
    overlap = sum(1 for k, y in enumerate(erg) if y is not None and 0 <= k + best < len(watch) and watch[k + best] is not None)
    if r < MIN_R:
        return {"offset_s": None, "signal": signal, "r": round(r, 3), "reason": "The two recordings never agree closely enough to propose an offset."}
    if r - rival < MIN_MARGIN:
        return {"offset_s": None, "signal": signal, "r": round(r, 3), "reason": "More than one offset fits about as well, so none is proposed."}
    return {"offset_s": best, "r": round(r, 3), "overlap_s": overlap, "signal": signal}
