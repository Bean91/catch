from __future__ import annotations

import math

# Paul's law: pace changes 5s/500m per doubling of distance (slower at longer distances).
# pace(target) = pace(known) - 5 * log2(known_distance / target_distance).
_SECONDS_PER_DOUBLING = 5.0


def predict_2k(pieces: list[dict], target_distance: float = 2000.0) -> dict:
    """pieces: [{"distance_m": float, "pace_s_per_500": float, "label": str}, ...] — the
    caller picks which recent best efforts to pass in; this just extrapolates each one."""
    components = []
    for piece in pieces:
        distance = piece.get("distance_m")
        pace = piece.get("pace_s_per_500")
        if not distance or not pace or distance <= 0 or pace <= 0:
            continue
        predicted_pace = pace - _SECONDS_PER_DOUBLING * math.log2(distance / target_distance)
        components.append(
            {
                "distance_m": distance,
                "pace_s_per_500": pace,
                "label": piece.get("label"),
                "predicted_2k_pace_s": predicted_pace,
            }
        )

    if not components:
        return {
            "value": None,
            "band": "insufficient_data",
            "components": [],
            "explanation": "No usable pieces (need distance_m and pace_s_per_500 on at least one recent effort).",
        }

    predicted_paces = [c["predicted_2k_pace_s"] for c in components]
    value = sum(predicted_paces) / len(predicted_paces)
    lo, hi = min(predicted_paces), max(predicted_paces)
    spread = hi - lo

    if len(components) >= 3 and spread <= 2.0:
        band = "high"
    elif len(components) >= 2:
        band = "moderate"
    else:
        band = "low"

    return {
        "value": value,
        "range": [lo, hi],
        "predicted_time_s": value * target_distance / 500.0,
        "band": band,
        "components": components,
        "explanation": (
            f"Paul's law (+{_SECONDS_PER_DOUBLING:.0f}s/500m per doubling of distance) "
            f"extrapolated from {len(components)} recent piece(s) to {target_distance:.0f}m."
        ),
    }
