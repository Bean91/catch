from __future__ import annotations

import math

# Concept2's published pace<->watts formula: watts = 2.80 / (seconds per meter)^3.
# Source: Concept2's "Watts Calculator" page / erg formula sheet (standard across rowing
# analytics tools). seconds_per_meter = pace_per_500m_seconds / 500.
# Worked values (session 34; the brief's own examples, 175/227/259/294 W, don't follow this formula):
# 2:00.0 → 202.5 W, 1:50.0 → 263.0 W, 1:45.0 → 302.3 W, 1:40.0 → 350.0 W.
# This is the ONE implementation; the browser asks the server (POST /api/pieces/preview) rather than keep a copy.
_WATTS_CONSTANT = 2.80
_METERS_PER_SPLIT = 500.0


def watts_from_pace(seconds_per_500m: float) -> float:
    if seconds_per_500m is None or not math.isfinite(seconds_per_500m) or seconds_per_500m <= 0:
        raise ValueError("pace must be a positive number of seconds")
    seconds_per_meter = seconds_per_500m / _METERS_PER_SPLIT
    return _WATTS_CONSTANT / (seconds_per_meter**3)


def pace_from_watts(watts: float) -> float:
    if watts is None or not math.isfinite(watts) or watts <= 0:
        raise ValueError("watts must be a positive number")
    seconds_per_meter = (_WATTS_CONSTANT / watts) ** (1 / 3)
    return seconds_per_meter * _METERS_PER_SPLIT


def _positive(value: float | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def w_per_kg(watts: float | None, weight_kg: float | None) -> float | None:
    if not _positive(watts) or not _positive(weight_kg):
        return None
    return watts / weight_kg


def weight_adjusted_power(watts: float | None, weight_kg: float | None) -> float | None:
    """Session 34: average power ÷ body mass^(2/3), in W/kg^(2/3) — power relative to size on the scaling that a body's
    power-producing cross-section follows (mass^(2/3)), so heavier and lighter rowers compare more fairly than with W/kg.
    Always from *average* power (never peak), never replacing the raw watts; None when either input is missing, zero or invalid.
    Body mass must already be kilograms (analytics/units.kg_from_lb converts pounds at the edge where they arrive)."""
    if not _positive(watts) or not _positive(weight_kg):
        return None
    return watts / weight_kg ** (2.0 / 3.0)
