from __future__ import annotations

"""Part E: zones/strain/session-label from the full per-sample HR (and power, where it
exists) stream rather than the whole-session average — pure functions, no I/O. The task's
own motivating case: a long warm-up/cool-down or a watch left running late drags average HR
down, so a session with real time at AN/TR shows up mislabeled as UT2 with an understated
strain. Everything here works on plain float lists (one value per second, None = missing),
built by catch/sync/samples.py from a FIT file's record messages or Concept2's stroke data.
"""

import math
from typing import Optional

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.analytics.zones import ZONE_ORDER, zone_for_hr, zone_for_power

DEFAULT_SMOOTHING_WINDOW_S = 5
DEFAULT_MIN_ZONE_MINUTES = 3.0
DEFAULT_MIN_ZONE_PCT = 0.10
DEFAULT_FLATLINE_RUN_S = 30  # a sensor "stuck" at one non-zero value this long is a dropout
DEFAULT_AUTO_TRIM_MIN_IDLE_S = 120


def drop_dropouts(samples: list[Optional[float]], flatline_run_s: int = DEFAULT_FLATLINE_RUN_S) -> list[Optional[float]]:
    """0 readings are always a dropout (a live HR of 0 doesn't happen); a run of the same
    non-zero value held for `flatline_run_s`+ samples is treated as a stuck sensor, not a
    genuinely flat heart rate (which doesn't happen for that long outside of a dropout)."""
    out = list(samples)
    n = len(out)
    i = 0
    while i < n:
        if out[i] is None:
            # Already a gap (e.g. a >10s resample dropout from catch/sync/fit_parse.py) —
            # nothing to clean here. Without this branch, the inner while below never
            # advances past a None (its own `is not None` guard means j stays == i), so i
            # never advances either: a real, confirmed infinite loop on any real sample
            # array with a gap in it (every one of this account's real activities has one).
            i += 1
            continue
        if out[i] == 0:
            out[i] = None
            i += 1
            continue
        j = i
        while j < n and out[j] is not None and out[j] == out[i]:
            j += 1
        if out[i] is not None and (j - i) >= flatline_run_s:
            for k in range(i, j):
                out[k] = None
        i = j
    return out


def smooth(samples: list[Optional[float]], window_s: int = DEFAULT_SMOOTHING_WINDOW_S) -> list[Optional[float]]:
    """Light centered moving average to drop sensor spikes, skipping None (dropout) samples
    in the window rather than treating them as 0."""
    n = len(samples)
    half = window_s // 2
    out: list[Optional[float]] = [None] * n
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        window = [v for v in samples[lo:hi] if v is not None]
        out[i] = sum(window) / len(window) if window else None
    return out


def time_in_zone_seconds(hr_samples: list[Optional[float]], max_hr: Optional[float], settings: dict | None = None) -> dict[str, float]:
    """Sums *actual* seconds in each zone from per-sample HR, rather than bucketing the
    whole session into the zone for its average — the specific fix the task's motivating
    case needs. Each sample represents 1 second by construction (catch/sync/samples.py
    resamples onto a 1 Hz grid)."""
    settings = settings or DEFAULT_SETTINGS
    totals = {z: 0.0 for z in ZONE_ORDER}
    if not max_hr:
        return totals
    for hr in hr_samples:
        if hr is None:
            continue
        zone = zone_for_hr(hr, max_hr, settings)
        if zone:
            totals[zone] += 1.0
    return totals


def power_time_in_zone_seconds(power_samples: list[Optional[float]], watts_2k: Optional[float], settings: dict | None = None) -> dict[str, float]:
    settings = settings or DEFAULT_SETTINGS
    totals = {z: 0.0 for z in ZONE_ORDER}
    if not watts_2k:
        return totals
    for w in power_samples:
        if w is None:
            continue
        zone = zone_for_power(w, watts_2k, settings)
        if zone:
            totals[zone] += 1.0
    return totals


def banister_trimp_from_samples(
    hr_samples: list[Optional[float]],
    resting_hr: Optional[float],
    max_hr: Optional[float],
    trimp_exponent: float = 1.92,
) -> Optional[float]:
    """Integrates Banister's per-minute TRIMP formula per *second* instead of once over the
    session average — a convex function of HRr, so concentrating the same total HR-minutes
    into a short, intense stretch (vs. spreading it evenly) necessarily scores higher. This is
    exactly why a 10-minute AN/TR block dominates the load while idle/warm-up minutes barely
    register, by construction rather than as a tuned special case."""
    if resting_hr is None or not max_hr or max_hr <= resting_hr:
        return None
    total = 0.0
    any_sample = False
    for hr in hr_samples:
        if hr is None:
            continue
        any_sample = True
        hrr = max(0.0, min(1.0, (hr - resting_hr) / (max_hr - resting_hr)))
        # 1 second = 1/60 minute; same 0.64*e^(b*HRr) weighting as the whole-session formula.
        total += (1.0 / 60.0) * hrr * 0.64 * math.exp(trimp_exponent * hrr)
    return total if any_sample else None


def session_label(
    hr_zone_seconds: dict[str, float],
    moving_time_s: float,
    power_zone_seconds: dict[str, float] | None = None,
    min_minutes: float = DEFAULT_MIN_ZONE_MINUTES,
    min_pct: float = DEFAULT_MIN_ZONE_PCT,
) -> str:
    """Classify by intensity distribution: the highest zone with "meaningful" time (either of
    the two configured floors clears it — see DEFAULT_MIN_ZONE_MINUTES/PCT) leads the label,
    with the zone that holds the most total time appended for context when it differs (e.g.
    "AN (10 min) + UT2" for a short hard effort inside a long easy session). HR and power
    zones (Part E.5, erg/bike) are each labelled independently and the higher-intensity one
    wins, since HR lags a short, sharp interval that power/pace already shows."""
    hr_label = _label_one(hr_zone_seconds, moving_time_s, min_minutes, min_pct)
    if not power_zone_seconds or not any(power_zone_seconds.values()):
        return hr_label
    power_label = _label_one(power_zone_seconds, moving_time_s, min_minutes, min_pct)
    hr_rank = _label_rank(hr_label)
    power_rank = _label_rank(power_label)
    return power_label if power_rank > hr_rank else hr_label


def _label_rank(label: str) -> int:
    primary = label.split(" ")[0]
    return ZONE_ORDER.index(primary) if primary in ZONE_ORDER else -1


def _label_one(zone_seconds: dict[str, float], moving_time_s: float, min_minutes: float, min_pct: float) -> str:
    if not zone_seconds or not any(zone_seconds.values()):
        return "No zone data"
    floor_s = min(min_minutes * 60.0, min_pct * moving_time_s) if moving_time_s else min_minutes * 60.0
    meaningful = [z for z in reversed(ZONE_ORDER) if zone_seconds.get(z, 0.0) >= floor_s]
    if not meaningful:
        # Nothing cleared the floor — fall back to whichever zone actually has the most time.
        primary = max(ZONE_ORDER, key=lambda z: zone_seconds.get(z, 0.0))
    else:
        primary = meaningful[0]
    secondary = max(ZONE_ORDER, key=lambda z: zone_seconds.get(z, 0.0))
    primary_minutes = round(zone_seconds.get(primary, 0.0) / 60.0)
    if secondary == primary:
        return f"{primary} ({primary_minutes} min)"
    return f"{primary} ({primary_minutes} min) + {secondary}"


def hr_recovery_drop(hr_full: list[Optional[float]], from_offset: int, window_s: int = 60) -> Optional[float]:
    """Drop in HR over `window_s` seconds starting at `from_offset` — shared by
    catch/api/routes_analytics.py's per-lap recovery (Part E.8) and catch/sync/piece.py's
    post-piece recovery (session 17 Part D.2). None if the recording doesn't extend far
    enough past `from_offset` to measure it, or either endpoint is a dropout."""
    if from_offset < 0 or from_offset >= len(hr_full):
        return None
    end = from_offset + window_s
    if end >= len(hr_full):
        return None
    start_hr, end_hr = hr_full[from_offset], hr_full[end]
    if start_hr is None or end_hr is None:
        return None
    return start_hr - end_hr


def detect_trailing_idle(movement_samples: list[Optional[float]], min_idle_s: int = DEFAULT_AUTO_TRIM_MIN_IDLE_S) -> float:
    """`movement_samples` is cadence/stroke-rate (or power), raw (not smoothed — trimming is
    about real stillness, not sensor noise). Returns the trailing run length in seconds of
    "effectively zero" movement at the very end of the recording, or 0.0 if it's shorter than
    `min_idle_s` or there's no movement signal at all (every value None — e.g. an HR-only
    strength session, where there's nothing to detect idle from)."""
    if not movement_samples or all(v is None for v in movement_samples):
        return 0.0
    n = len(movement_samples)
    i = n - 1
    while i >= 0 and (movement_samples[i] is None or movement_samples[i] <= 1.0):
        i -= 1
    trailing = n - 1 - i
    return float(trailing) if trailing >= min_idle_s else 0.0
