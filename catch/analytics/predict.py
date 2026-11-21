"""2k estimate from real erg performances (session 32 rewrite — docs/analytics.md §2). Pure: the caller gathers the evidence.

The relation is Paul's law, the standard rowing rule of thumb: pace rises about 5 s/500 m per doubling of distance. What session 32
changed is *which* performances feed it and *how*:

* Only efforts that were plausibly maximal: a confirmed test or a confirmed single-effort piece (declared), or a continuous result
  whose average heart rate was at least 85 % of max (heart-rate verified). A result with no heart rate is admitted only as weak
  evidence. Steady rows, intervals, rate-capped pieces and anything outside 500 m–10 km never count.
* Recent evidence wins: when any declared or verified effort exists in the last 120 days only that window is used; older data is a
  fallback that caps confidence at "low" and says so.
* Submaximal efforts can only make an estimate too slow, so points more than 4 % slower than the best near-2,000 m effort are dropped
  (a declared effort within one doubling of 2,000 m never is), then the estimate is the weighted median (recency half-life 60 days x
  effort class x closeness to 2,000 m).
* The range adds the spread between points, the uncertainty of Paul's law itself per doubling extrapolated, a day-to-day floor and
  a staleness term. Confidence is stated in words and never "high" without two recent strong efforts near 2,000 m.

Nothing here ever replaces a measured 2k: the caller reports the latest confirmed 2k test separately."""

from __future__ import annotations

import math
from datetime import date

SECONDS_PER_DOUBLING = 5.0  # Paul's law, s/500 m
# How far one athlete's own curve can sit from 5 s per doubling (rowers measure roughly 3-7): the extrapolation part of the range.
LAW_UNCERTAINTY_PER_DOUBLING = 2.0  # s/500 m
DAY_TO_DAY_FLOOR_S = 2.0  # on a 2k time
MIN_DISTANCE_M = 500.0
MAX_DISTANCE_M = 10_000.0
HALF_LIFE_DAYS = 60.0
RECENT_DAYS = 120
LOOKBACK_DAYS = 365
NEAR_BEST = 0.04
STALE_AFTER_DAYS = 28
STALE_S_PER_WEEK = 0.5
STALE_CAP_S = 10.0
EFFORT_WEIGHT = {"declared": 1.0, "hr_verified": 0.7, "effort_unknown": 0.3}
HR_VERIFIED_FRACTION = 0.85


def pace_per_500(distance_m: float, duration_s: float) -> float:
    return duration_s / distance_m * 500.0


def implied_2k_time(distance_m: float, duration_s: float, target_m: float = 2000.0) -> float:
    """The 2k time this one performance implies under Paul's law (seconds)."""
    pace = pace_per_500(distance_m, duration_s)
    return (pace - SECONDS_PER_DOUBLING * math.log2(distance_m / target_m)) * target_m / 500.0


def effort_class(*, declared: bool, avg_hr: float | None, max_hr: float | None) -> str | None:
    """'declared' (a confirmed test or piece), 'hr_verified' (avg HR >= 85 % of max), 'effort_unknown' (no HR to tell), or None
    for a recorded effort whose heart rate shows it was steady (never used)."""
    if declared:
        return "declared"
    if avg_hr is None or not max_hr:
        return "effort_unknown"
    return "hr_verified" if avg_hr >= HR_VERIFIED_FRACTION * max_hr else None


def _weighted_median(values: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights))
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


def _weighted_sd(values: list[float], weights: list[float]) -> float:
    total = sum(weights)
    if len(values) < 2 or total <= 0:
        return 0.0
    mean = sum(v * w for v, w in zip(values, weights)) / total
    return math.sqrt(sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / total)


def _fmt(seconds: float) -> str:
    m, s = divmod(round(seconds, 1), 60)
    return f"{int(m)}:{s:04.1f}"


def predict_2k(points: list[dict], as_of: date, target_distance: float = 2000.0) -> dict:
    """points: [{"distance_m", "duration_s", "date": date, "effort": effort_class(...), "label", "canonical_id"?}, ...].

    Returns the estimate (seconds and pace), a range in seconds, a confidence word and the evidence used — plus the pre-session-32
    keys (`value` = pace s/500 m, `range` = pace s/500 m, `predicted_time_s`, `band`, `components`) so existing readers keep working."""
    qualified = []
    for p in points:
        d, t, day, effort = p.get("distance_m"), p.get("duration_s"), p.get("date"), p.get("effort")
        if not d or not t or d <= 0 or t <= 0 or effort not in EFFORT_WEIGHT or day is None:
            continue
        if not (MIN_DISTANCE_M <= d <= MAX_DISTANCE_M):
            continue
        age = (as_of - day).days
        if age < 0 or age > LOOKBACK_DAYS:
            continue
        doublings = abs(math.log2(d / target_distance))
        weight = 0.5 ** (age / HALF_LIFE_DAYS) * EFFORT_WEIGHT[effort] / (1.0 + doublings)
        qualified.append({**p, "age_days": age, "doublings": doublings, "weight": weight, "implied_2k_s": implied_2k_time(d, t, target_distance)})

    if not qualified:
        return _insufficient("No qualifying effort in the last year: a confirmed test or piece, or a continuous row of 500 m to 10 km "
                             "hard enough to show it (average heart rate at least 85 % of max).")
    strong = [q for q in qualified if q["effort"] != "effort_unknown"]
    recent_strong = [q for q in strong if q["age_days"] <= RECENT_DAYS]
    if not strong and all(q["age_days"] > RECENT_DAYS for q in qualified):
        return _insufficient("Only older rows with no heart rate to show they were hard efforts — log a test or a piece.")

    recent = [q for q in qualified if q["age_days"] <= RECENT_DAYS]
    stale = bool(strong) and not recent_strong
    pool = recent if (recent_strong or not strong) else qualified
    reference_pool = [q for q in pool if q["effort"] != "effort_unknown"] or pool
    # The reference comes from efforts within one doubling of 2,000 m when there are any: Paul's law from a 500 m sprint usually
    # flatters a sprint-strong rower, and must not be the yardstick that discards a real 2k. A declared effort that close to
    # 2,000 m is never dropped.
    reference_pool = [q for q in reference_pool if q["doublings"] <= 1.0] or reference_pool
    best = min(q["implied_2k_s"] for q in reference_pool)
    kept = [q for q in pool if q["implied_2k_s"] <= best * (1 + NEAR_BEST) or (q["effort"] == "declared" and q["doublings"] <= 1.0)]
    values = [q["implied_2k_s"] for q in kept]
    weights = [q["weight"] for q in kept]
    estimate = _weighted_median(values, weights)

    total_w = sum(weights)
    mean_doublings = sum(q["doublings"] * q["weight"] for q in kept) / total_w
    extrapolation_s = LAW_UNCERTAINTY_PER_DOUBLING * mean_doublings * target_distance / 500.0
    spread_s = _weighted_sd(values, weights)
    newest_age = min(q["age_days"] for q in kept)
    staleness_s = min(STALE_CAP_S, max(0, newest_age - STALE_AFTER_DAYS) / 7.0 * STALE_S_PER_WEEK)
    half = math.sqrt(extrapolation_s**2 + spread_s**2 + DAY_TO_DAY_FLOOR_S**2) + staleness_s
    lo, hi = estimate - half, estimate + half

    near_strong = [q for q in kept if q["effort"] != "effort_unknown" and q["age_days"] <= 90]
    if stale:
        confidence = "low"
    elif len(near_strong) >= 2 and any(q["doublings"] <= 1.0 for q in near_strong) and half <= 4.0:
        confidence = "high"
    elif any(q["effort"] != "effort_unknown" and q["doublings"] <= 1.6 for q in kept) and half <= 8.0:
        confidence = "moderate"
    else:
        confidence = "low"

    reasons = []
    if stale:
        reasons.append("no hard effort in the last 4 months, so this leans on older data")
    if all(q["effort"] == "effort_unknown" for q in kept):
        reasons.append("none of these rows has heart rate to show it was a hard effort, so it may be too slow")
    if mean_doublings > 1.0:
        reasons.append("it extrapolates from distances well away from 2,000 m")
    pace = estimate * 500.0 / target_distance
    components = [
        {
            "distance_m": q["distance_m"], "duration_s": q["duration_s"], "pace_s_per_500": pace_per_500(q["distance_m"], q["duration_s"]),
            "date": q["date"].isoformat(), "age_days": q["age_days"], "effort": q["effort"], "label": q.get("label"),
            "canonical_id": q.get("canonical_id"), "implied_2k_s": q["implied_2k_s"], "predicted_2k_pace_s": q["implied_2k_s"] * 500.0 / target_distance,
            "weight": round(q["weight"] / total_w, 4),
        }
        for q in sorted(kept, key=lambda q: q["date"], reverse=True)
    ]
    explanation = (
        f"Estimated from {len(kept)} effort(s) using Paul's law (+{SECONDS_PER_DOUBLING:.0f} s/500 m per doubling of distance), "
        f"recent and near-2,000 m efforts weighted most: {_fmt(estimate)} (likely {_fmt(lo)}–{_fmt(hi)})."
        + (" Less certain because " + "; ".join(reasons) + "." if reasons else "")
        + " An estimate, not a measured result."
    )
    return {
        "kind": "estimate",
        "value": pace,
        "range": [lo * 500.0 / target_distance, hi * 500.0 / target_distance],
        "predicted_time_s": estimate,
        "range_s": [lo, hi],
        "band": confidence,
        "confidence": confidence,
        "stale": stale,
        "components": components,
        "excluded_count": len(qualified) - len(kept),
        "explanation": explanation,
    }


def _insufficient(reason: str) -> dict:
    return {
        "kind": "estimate",
        "value": None,
        "range": None,
        "predicted_time_s": None,
        "range_s": None,
        "band": "insufficient_data",
        "confidence": "insufficient_data",
        "stale": False,
        "components": [],
        "excluded_count": 0,
        "explanation": reason,
    }
