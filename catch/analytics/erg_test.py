from __future__ import annotations

"""Session 15 (see PLAN.md Part C): erg test center. Pure, no I/O."""

from datetime import date

# Standard test types (task Part C.1) plus "custom". Distance-based tests match on
# distance_m within a tolerance; duration-based ones match on duration_s. "30min_r20"
# additionally needs an average stroke rate at or below ~20 — distinguishing a real
# steady-state r20 test from an all-out 30-minute piece at a much higher rate, which would
# otherwise also land inside the duration tolerance.
TEST_SPECS: dict[str, dict] = {
    "500m": {"distance_m": 500},
    "1000m": {"distance_m": 1000},
    "2000m": {"distance_m": 2000},
    "5000m": {"distance_m": 5000},
    "6000m": {"distance_m": 6000},
    "30min_r20": {"duration_s": 1800, "max_avg_rate": 20.5},
    "60min": {"duration_s": 3600},
}
_DISTANCE_TOLERANCE_PCT = 0.02
_DURATION_TOLERANCE_S = 25.0
_STYLES = ("even", "fast_start_settle", "negative_split")


def detect_test_type(distance_m: float | None, duration_s: float | None, avg_stroke_rate: float | None) -> str | None:
    """Best matching standard type, or None (the caller should offer "custom" instead of
    forcing a bad match — task Part C.1's auto-detect is a suggestion to confirm, never an
    automatic tag)."""
    for name, spec in TEST_SPECS.items():
        if "distance_m" in spec:
            if not distance_m:
                continue
            target = spec["distance_m"]
            tolerance = max(10.0, target * _DISTANCE_TOLERANCE_PCT)
            if abs(distance_m - target) <= tolerance:
                return name
        else:
            if not duration_s:
                continue
            target = spec["duration_s"]
            if abs(duration_s - target) <= _DURATION_TOLERANCE_S:
                max_rate = spec.get("max_avg_rate")
                if max_rate is not None and (avg_stroke_rate is None or avg_stroke_rate > max_rate):
                    continue
                return name
    return None


def _style_multipliers(n: int, style: str) -> list[float]:
    if style not in _STYLES:
        raise ValueError(f"style must be one of {_STYLES}")
    if style == "even" or n <= 1:
        return [1.0] * n
    if style == "fast_start_settle":
        head = max(1, round(n * 0.25))
        tail = max(1, round(n * 0.25))
        mid = max(0, n - head - tail)
        return [0.985] * head + [1.0] * mid + [1.015] * tail
    # negative_split: first half a touch slower, second half a touch faster.
    first_half = (n + 1) // 2
    return [1.01] * first_half + [0.99] * (n - first_half)


def pacing_plan(distance_m: float, goal_time_s: float, style: str, rate_hint: float | None = None) -> dict:
    """Per-500m targets (task Part C.3) — illustrative pacing shapes (±1-1.5% off even
    split), not a validated prescription, same honesty as every other illustrative default
    in this app (see docs/analytics.md). Splits are scaled so they always sum to exactly
    `goal_time_s`, whatever shape the style picks."""
    if distance_m <= 0 or goal_time_s <= 0:
        raise ValueError("distance_m and goal_time_s must be positive")
    n_splits = max(1, round(distance_m / 500))
    base_split = goal_time_s / n_splits
    multipliers = _style_multipliers(n_splits, style)
    raw = [base_split * m for m in multipliers]
    scale = goal_time_s / sum(raw)
    splits = [s * scale for s in raw]

    rows, cum = [], 0.0
    for i, split_s in enumerate(splits):
        cum += split_s
        rows.append(
            {
                "split_index": i + 1,
                "distance_m": min((i + 1) * 500, distance_m),
                "target_split_s": split_s,
                "target_cum_s": cum,
            }
        )
    return {
        "style": style,
        "distance_m": distance_m,
        "goal_time_s": goal_time_s,
        "rate_hint": rate_hint,
        "splits": rows,
        "explanation": (
            f"{n_splits} x 500m targets for a {style.replace('_', ' ')} pacing shape, scaled "
            f"to total exactly {goal_time_s:.1f}s."
        ),
    }


def _time_at_distance(points: list[dict], target: float) -> float | None:
    """Linear interpolation of cumulative time at `target` metres, from a series of
    {"distance_cum", "t_cum"} points sorted by distance."""
    prev = None
    for p in points:
        d, t = p.get("distance_cum"), p.get("t_cum")
        if d is None or t is None:
            continue
        if d >= target:
            if prev is None:
                return t
            d0, t0 = prev["distance_cum"], prev["t_cum"]
            if d == d0:
                return t
            frac = (target - d0) / (d - d0)
            return t0 + frac * (t - t0)
        prev = {"distance_cum": d, "t_cum": t}
    return None


def actual_splits(points: list[dict], distance_m: float) -> list[dict]:
    n = max(1, round(distance_m / 500))
    marks = [min((i + 1) * 500, distance_m) for i in range(n)]
    rows, prev_t = [], 0.0
    for i, mark in enumerate(marks):
        t = _time_at_distance(points, mark)
        split = (t - prev_t) if t is not None else None
        rows.append({"split_index": i + 1, "distance_m": mark, "actual_split_s": split, "actual_cum_s": t})
        if t is not None:
            prev_t = t
    return rows


def pacing_analysis(points: list[dict], distance_m: float, plan: dict | None = None) -> dict:
    """task Part C.2: start/middle-1000/sprint breakdown, deviation from even split, where
    the time was lost — plus a split-by-split comparison against a saved plan, if any."""
    splits = actual_splits(points, distance_m)
    valid = [r for r in splits if r["actual_split_s"] is not None]
    valid_values = [r["actual_split_s"] for r in valid]
    even_split_s = (sum(valid_values) / len(valid_values)) if valid_values else None

    n = len(splits)
    start_n = max(1, round(n * 0.25))
    sprint_n = max(1, round(n * 0.15))
    start = [r["actual_split_s"] for r in splits[:start_n] if r["actual_split_s"] is not None]
    sprint = [r["actual_split_s"] for r in splits[-sprint_n:] if r["actual_split_s"] is not None]
    middle_rows = splits[start_n : max(start_n, n - sprint_n)]
    middle = [r["actual_split_s"] for r in middle_rows if r["actual_split_s"] is not None]

    def _avg(xs: list[float]) -> float | None:
        return (sum(xs) / len(xs)) if xs else None

    worst_split, deviation_pct = None, None
    if even_split_s and valid_values:
        worst = max(valid, key=lambda r: r["actual_split_s"])
        worst_split = {"split_index": worst["split_index"], "seconds_lost_vs_even": worst["actual_split_s"] - even_split_s}
        deviation_pct = (max(valid_values) - min(valid_values)) / even_split_s * 100

    vs_plan = None
    if plan:
        plan_by_idx = {s["split_index"]: s for s in plan["splits"]}
        vs_plan = [
            {
                "split_index": r["split_index"],
                "actual_s": r["actual_split_s"],
                "target_s": plan_by_idx[r["split_index"]]["target_split_s"],
                "delta_s": r["actual_split_s"] - plan_by_idx[r["split_index"]]["target_split_s"],
            }
            for r in splits
            if r["actual_split_s"] is not None and r["split_index"] in plan_by_idx
        ]

    return {
        "splits": splits,
        "even_split_s": even_split_s,
        "segments": {"start": _avg(start), "middle_1000": _avg(middle), "sprint": _avg(sprint)},
        "deviation_from_even_pct": deviation_pct,
        "worst_split_vs_even": worst_split,
        "vs_plan": vs_plan,
    }


def project_time(history: list[tuple[date, float]], target_date: date) -> dict:
    """A linear trend over this test type's history, projected to `target_date` (task Part
    C.4's "projected 2k on the date of my next A race"), with a ±1-residual-SD band — a
    prediction interval around the trend line, not a confidence interval on the slope
    itself. Deliberately refuses with fewer than 3 points rather than fitting a line through
    noise; the inputs are always listed so the number is checkable."""
    inputs = [{"date": d.isoformat(), "value": v} for d, v in history]
    if len(history) < 3:
        return {
            "value": None,
            "range": None,
            "explanation": f"Need at least 3 tests of this type to project a trend; have {len(history)}.",
            "inputs": inputs,
        }
    x0 = history[0][0]
    xs = [(d - x0).days for d, _ in history]
    ys = [v for _, v in history]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / var_x if var_x > 0 else 0.0
    intercept = mean_y - slope * mean_x
    target_x = (target_date - x0).days
    predicted = intercept + slope * target_x
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    resid_sd = (sum(r * r for r in residuals) / (n - 2)) ** 0.5 if n > 2 else (max(residuals) - min(residuals)) / 2
    return {
        "value": predicted,
        "range": [predicted - resid_sd, predicted + resid_sd],
        "slope_s_per_day": slope,
        "n_points": n,
        "explanation": (
            f"Linear trend over {n} tests of this type, projected to {target_date.isoformat()}; "
            f"band is ±1 residual SD ({resid_sd:.1f}s) around the trend line, not a statement "
            "about how confident the slope itself is."
        ),
        "inputs": inputs,
    }
