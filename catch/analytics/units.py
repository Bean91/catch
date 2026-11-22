from __future__ import annotations

import math

# The international avoirdupois pound, exactly (1959 agreement).
KG_PER_LB = 0.45359237
BODY_MASS_UNITS = ("kg", "lb")


def kg_from_lb(pounds: float) -> float:
    if pounds is None or not math.isfinite(pounds) or pounds <= 0:
        raise ValueError("pounds must be a positive number")
    return pounds * KG_PER_LB


def body_mass_kg(value: float, unit: str) -> float:
    """A body mass as entered, in kilograms. Every stored weight is kilograms; this is the one place another unit is converted."""
    if unit not in BODY_MASS_UNITS:
        raise ValueError(f"unit must be one of {list(BODY_MASS_UNITS)}")
    return kg_from_lb(value) if unit == "lb" else float(value)
