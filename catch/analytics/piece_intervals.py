from __future__ import annotations

"""Session 19 (see PLAN.md): structured intervals within a piece — pure functions, no I/O.

An interval row is a dict: {position, target_type ("distance"|"time"), work_distance_m,
work_duration_s, rest_duration_s, avg_split_s, avg_watts, avg_rate, avg_hr, max_hr, calories,
notes}. `target_type` says which side was *prescribed*; the other side is what the athlete
achieved and may still be empty (an incomplete interval is a normal, saveable state). Rest
belongs to the work interval it follows — never its own row — so "rest between 4x500m" is
3 rests plus an optional trailing one."""

from typing import Optional

TARGET_TYPES = ("distance", "time")
MAX_INTERVALS = 100
RATE_RANGE = (14.0, 50.0)
MAX_WORK_DISTANCE_M = 100_000.0
MAX_DURATION_S = 12 * 3600.0
# Split (s/500m) and the row's own time/distance may disagree this much before it's flagged —
# generous because a typed split is read off a PM5 screen and rounded.
_SPLIT_TOLERANCE_PCT = 0.03
_NUMERIC = ("work_distance_m", "work_duration_s", "rest_duration_s", "avg_split_s", "avg_watts", "avg_rate", "avg_hr", "max_hr", "calories")


def derived_split_s(row: dict) -> Optional[float]:
    if row.get("avg_split_s") is not None:
        return row["avg_split_s"]
    d, t = row.get("work_distance_m"), row.get("work_duration_s")
    if d and t and d > 0:
        return t / d * 500.0
    return None


def validate_intervals(rows: list[dict]) -> dict:
    """Same `{ok, issues: [{index, field, message}]}` shape as piece.validate_splits. Never
    corrects a row. `index` is the row's position in the list (None = list-level)."""
    issues: list[dict] = []

    def add(index: Optional[int], field: Optional[str], message: str) -> None:
        issues.append({"index": index, "field": field, "message": message})

    if len(rows) > MAX_INTERVALS:
        add(None, None, f"At most {MAX_INTERVALS} intervals per piece.")
    positions = [r.get("position") for r in rows]
    if positions != list(range(len(rows))):
        add(None, "position", "Interval positions must be 0..n-1 with no duplicates or gaps.")

    for i, r in enumerate(rows):
        for f in _NUMERIC:
            v = r.get(f)
            if v is not None and v < 0:
                add(i, f, f"{f} can't be negative.")
        if r.get("target_type") not in TARGET_TYPES:
            add(i, "target_type", "target_type must be 'distance' or 'time'.")
            continue
        target_field = "work_distance_m" if r["target_type"] == "distance" else "work_duration_s"
        if not r.get(target_field):
            add(i, target_field, "A work target greater than zero is required.")
        d, t = r.get("work_distance_m"), r.get("work_duration_s")
        if d is not None and d > MAX_WORK_DISTANCE_M:
            add(i, "work_distance_m", "Distance is implausibly large.")
        for f in ("work_duration_s", "rest_duration_s"):
            if r.get(f) is not None and r[f] > MAX_DURATION_S:
                add(i, f, "Duration is implausibly long.")
        rate = r.get("avg_rate")
        if rate is not None and not (RATE_RANGE[0] <= rate <= RATE_RANGE[1]):
            add(i, "avg_rate", f"Stroke rate should be {RATE_RANGE[0]:.0f}-{RATE_RANGE[1]:.0f} spm.")
        if r.get("max_hr") is not None and r.get("avg_hr") is not None and r["max_hr"] < r["avg_hr"]:
            add(i, "max_hr", "Max HR can't be below average HR.")
        if r.get("avg_hr") is not None and not (30 <= r["avg_hr"] <= 230):
            add(i, "avg_hr", "Average HR is outside a plausible range.")
        if r.get("avg_split_s") is not None and d and t and d > 0:
            implied = t / d * 500.0
            if abs(implied - r["avg_split_s"]) > max(1.0, implied * _SPLIT_TOLERANCE_PCT):
                add(i, "avg_split_s", "Split doesn't match this interval's distance and time.")
    return {"ok": not issues, "issues": issues}


def expand_repeat(
    count: int,
    *,
    work_distance_m: Optional[float] = None,
    work_duration_s: Optional[float] = None,
    rest_duration_s: Optional[float] = None,
    start_position: int = 0,
) -> list[dict]:
    """"4 x 500m r1:00" -> four empty-metric rows. Exactly one of distance/duration is the
    prescription. The trailing interval gets no rest: nothing follows it."""
    if count < 1 or count > MAX_INTERVALS:
        raise ValueError(f"count must be 1-{MAX_INTERVALS}")
    if (work_distance_m is None) == (work_duration_s is None):
        raise ValueError("Give exactly one of work_distance_m or work_duration_s")
    target = work_distance_m if work_distance_m is not None else work_duration_s
    if not target or target <= 0:
        raise ValueError("Work target must be greater than zero")
    rows = []
    for i in range(count):
        rows.append(
            {
                "position": start_position + i,
                "target_type": "distance" if work_distance_m is not None else "time",
                "work_distance_m": work_distance_m,
                "work_duration_s": work_duration_s,
                "rest_duration_s": rest_duration_s if (rest_duration_s and i < count - 1) else None,
                "avg_split_s": None,
                "avg_watts": None,
                "avg_rate": None,
                "avg_hr": None,
                "max_hr": None,
                "calories": None,
                "notes": None,
            }
        )
    return rows


def _weighted(rows: list[dict], field: str) -> Optional[float]:
    """Time-weighted mean over only the rows that have both the metric and a work duration —
    a missing value is skipped, never counted as zero."""
    num = den = 0.0
    for r in rows:
        v, t = r.get(field), r.get("work_duration_s")
        if v is None or not t:
            continue
        num += v * t
        den += t
    return num / den if den else None


def summarize_intervals(rows: list[dict]) -> dict:
    """Totals and weighted averages. The piece-level split is total time / total distance over
    the rows that carry *both* (not a mean of interval splits, and not distorted by a row that
    only has one); watts/rate/HR are weighted by work time."""
    work_distance = sum(r["work_distance_m"] for r in rows if r.get("work_distance_m")) or 0.0
    work_duration = sum(r["work_duration_s"] for r in rows if r.get("work_duration_s")) or 0.0
    rest = sum(r["rest_duration_s"] for r in rows if r.get("rest_duration_s")) or 0.0
    both = [r for r in rows if r.get("work_distance_m") and r.get("work_duration_s")]
    both_d = sum(r["work_distance_m"] for r in both)
    both_t = sum(r["work_duration_s"] for r in both)
    max_hrs = [r["max_hr"] for r in rows if r.get("max_hr") is not None] + [r["avg_hr"] for r in rows if r.get("avg_hr") is not None and r.get("max_hr") is None]
    calories = [r["calories"] for r in rows if r.get("calories") is not None]
    # "Complete" = the target side plus the achieved other side are both present.
    complete = sum(1 for r in rows if r.get("work_distance_m") and r.get("work_duration_s"))
    return {
        "count": len(rows),
        "complete_count": complete,
        "work_distance_m": work_distance or None,
        "work_duration_s": work_duration or None,
        "rest_duration_s": rest or None,
        "total_duration_s": (work_duration + rest) or None,
        "avg_split_s": (both_t / both_d * 500.0) if both_d else None,
        "avg_watts": _weighted(rows, "avg_watts"),
        "avg_rate": _weighted(rows, "avg_rate"),
        "avg_hr": _weighted(rows, "avg_hr"),
        "max_hr": max(max_hrs) if max_hrs else None,
        "calories": sum(calories) if calories else None,
    }


def _fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def interval_signature(rows: list[dict]) -> Optional[str]:
    """Equivalence key for comparing sessions: same prescription => same key. A uniform set
    reads "4x500m/r60"; anything else lists each interval in order. Rest on the final interval
    is ignored (nothing follows it)."""
    if not rows:
        return None
    parts = []
    for i, r in enumerate(rows):
        target = r.get("work_distance_m") if r.get("target_type") == "distance" else r.get("work_duration_s")
        if not target:
            return None
        unit = "m" if r.get("target_type") == "distance" else "s"
        rest = r.get("rest_duration_s") if i < len(rows) - 1 else None
        parts.append((f"{_fmt_num(target)}{unit}", int(round(rest)) if rest else 0))
    if _uniform(parts):
        return f"{len(parts)}x{parts[0][0]}/r{parts[0][1]}"
    return "+".join(f"{w}/r{rest}" for w, rest in parts)


def _uniform(parts: list[tuple[str, int]]) -> bool:
    work = {w for w, _ in parts}
    rests = {r for _, r in parts[:-1]}
    return len(work) == 1 and len(rests) <= 1
