from __future__ import annotations

import statistics

# Each stroke dict here is {"t": seconds_elapsed_in_piece, "distance": meters_elapsed_in_piece,
# "watts": float|None, "stroke_rate": float|None, "pace_500m": float|None} — one piece/interval
# worth, already picked out by the caller (catch.api.routes_analytics groups by Stroke.interval_index).


def _cumulative_points(strokes: list[dict]) -> list[tuple[float, float]]:
    pts = [(s["distance"], s["t"]) for s in strokes if s.get("distance") is not None and s.get("t") is not None]
    return sorted(pts)


def _split_times(strokes: list[dict], split_distance: float = 500.0) -> list[float]:
    pts = _cumulative_points(strokes)
    if len(pts) < 2:
        return []
    total_distance = pts[-1][0]
    n_splits = int(total_distance // split_distance)
    times = []
    prev_t = 0.0
    idx = 0
    for k in range(1, n_splits + 1):
        target_d = k * split_distance
        while idx < len(pts) - 1 and pts[idx + 1][0] < target_d:
            idx += 1
        d0, t0 = pts[idx]
        d1, t1 = pts[min(idx + 1, len(pts) - 1)]
        t_at = t0 if d1 == d0 else t0 + (target_d - d0) / (d1 - d0) * (t1 - t0)
        times.append(t_at - prev_t)
        prev_t = t_at
    return times


def split_consistency(strokes: list[dict]) -> dict:
    splits = _split_times(strokes)
    if len(splits) < 2:
        return {
            "value": None,
            "band": "insufficient_data",
            "components": [],
            "explanation": "Need at least two full 500m splits in this piece.",
        }
    mean = statistics.mean(splits)
    cv = (statistics.pstdev(splits) / mean * 100) if mean else None
    band = "insufficient_data" if cv is None else "consistent" if cv < 3 else "moderate" if cv < 6 else "variable"
    return {
        "value": cv,
        "band": band,
        "components": [{"split_times_s": splits}],
        "explanation": f"Coefficient of variation (stdev/mean x100) across {len(splits)} x 500m splits.",
    }


def watts_per_stroke(strokes: list[dict]) -> dict:
    joules = [s["watts"] * 60.0 / s["stroke_rate"] for s in strokes if s.get("watts") and s.get("stroke_rate")]
    if not joules:
        return {
            "value": None,
            "band": "insufficient_data",
            "components": [],
            "explanation": "Need both watts and stroke_rate on strokes.",
        }
    return {
        "value": statistics.mean(joules),
        "band": "n/a",
        "components": [{"n": len(joules)}],
        "explanation": "Mean of (watts x 60/stroke_rate) — work (joules-equivalent) done per stroke.",
    }


def rate_power_slope(strokes: list[dict]) -> dict:
    pairs = [(s["stroke_rate"], s["watts"]) for s in strokes if s.get("stroke_rate") and s.get("watts")]
    if len(pairs) < 3:
        return {
            "value": None,
            "band": "insufficient_data",
            "components": [],
            "explanation": "Need at least 3 strokes with both stroke_rate and watts.",
        }
    n = len(pairs)
    sx = sum(x for x, _ in pairs)
    sy = sum(y for _, y in pairs)
    sxx = sum(x * x for x, _ in pairs)
    sxy = sum(x * y for x, y in pairs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return {
            "value": None,
            "band": "insufficient_data",
            "components": [],
            "explanation": "No variance in stroke rate across this piece.",
        }
    slope = (n * sxy - sx * sy) / denom
    band = "efficient" if slope >= 8 else "typical" if slope >= 4 else "inefficient"
    return {
        "value": slope,
        "band": band,
        "components": [{"n": n}],
        "explanation": (
            "Least-squares slope of watts vs stroke rate (W per stroke/min). Higher means more "
            "power gained per unit of rate increase (driving with the legs, not just rating up) "
            "— illustrative heuristic, not a validated technique score."
        ),
    }


def fade(strokes: list[dict]) -> dict:
    ordered = sorted(strokes, key=lambda s: s.get("t", 0))
    n = len(ordered)
    if n < 8:
        return {
            "value": None,
            "band": "insufficient_data",
            "components": [],
            "explanation": "Need at least 8 strokes to compare first/last quarters.",
        }
    q = max(1, n // 4)
    first, last = ordered[:q], ordered[-q:]

    def avg_pace(segment: list[dict]) -> float | None:
        paces = [s["pace_500m"] for s in segment if s.get("pace_500m")]
        return statistics.mean(paces) if paces else None

    first_pace, last_pace = avg_pace(first), avg_pace(last)
    if not first_pace or last_pace is None:
        return {
            "value": None,
            "band": "insufficient_data",
            "components": [],
            "explanation": "Need pace_500m on both the first and last quarter of strokes.",
        }
    fade_pct = (last_pace - first_pace) / first_pace * 100
    band = "held_pace" if fade_pct <= 1 else "mild_fade" if fade_pct <= 3 else "faded"
    return {
        "value": fade_pct,
        "band": band,
        "components": [{"first_quarter_pace_s": first_pace, "last_quarter_pace_s": last_pace, "n_per_quarter": q}],
        "explanation": "% slower pace in the last quarter of strokes vs the first quarter; positive = faded.",
    }


def erg_technique(strokes: list[dict]) -> dict:
    return {
        "split_consistency": split_consistency(strokes),
        "watts_per_stroke": watts_per_stroke(strokes),
        "rate_power_slope": rate_power_slope(strokes),
        "fade": fade(strokes),
    }
