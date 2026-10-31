from __future__ import annotations

# Concept2's published pace<->watts formula: watts = 2.80 / (seconds per meter)^3.
# Source: Concept2's "Watts Calculator" page / erg formula sheet (standard across rowing
# analytics tools). seconds_per_meter = pace_per_500m_seconds / 500.
_WATTS_CONSTANT = 2.80
_METERS_PER_SPLIT = 500.0


def watts_from_pace(seconds_per_500m: float) -> float:
    if seconds_per_500m <= 0:
        raise ValueError("pace must be positive")
    seconds_per_meter = seconds_per_500m / _METERS_PER_SPLIT
    return _WATTS_CONSTANT / (seconds_per_meter**3)


def pace_from_watts(watts: float) -> float:
    if watts <= 0:
        raise ValueError("watts must be positive")
    seconds_per_meter = (_WATTS_CONSTANT / watts) ** (1 / 3)
    return seconds_per_meter * _METERS_PER_SPLIT


def w_per_kg(watts: float | None, weight_kg: float | None) -> float | None:
    if watts is None or weight_kg is None or weight_kg <= 0:
        return None
    return watts / weight_kg
