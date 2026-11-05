from __future__ import annotations

"""Equipment load math for the gym logger (session 14 — see PLAN.md Part A.3). Pure
functions, no I/O, per CLAUDE.md's analytics convention.

`effective_load_kg` is "the actual resistance the lifter moved," used by
catch/analytics/strength.py's muscular-load math — never a motivational "number on the
plates." Every equipment type below converts whatever the lifter actually reads off the
equipment into that one number.

Smith/cable conventions (there's no universal standard, so these are documented, not
assumed): a Smith machine's `load_kg` is the plates added (what the lifter reads off the
machine), not a total — the bar's own counterweight is a separate, per-gym `bar_weight_kg`
("many are counterbalanced, often 6-15kg instead of 20kg" — task Part A.3), added on top. A
cable station's `load_kg` is the stack number shown; `pulley_multiplier` converts it to felt
resistance (1.0 for 1:1, 0.5 for a 2:1 block-and-tackle that halves the felt load, 0.25 for
4:1) — stack numbers are only ever compared within the same station, never across stations
with different multipliers, per CLAUDE.md's task note.
"""

from dataclasses import dataclass
from typing import Optional

DEFAULT_BARBELL_KG = 20.0
DEFAULT_UNKNOWN_SMITH_BAR_KG = 10.0  # a rough mid-point guess, always flagged as estimated.

DEFAULT_PLATES_KG = [25.0, 20.0, 15.0, 10.0, 5.0, 2.5, 1.25]
DEFAULT_PLATES_LB = [45.0, 35.0, 25.0, 10.0, 5.0, 2.5]

# Approximate resistance for a tagged resistance band, since band tension varies continuously
# with stretch and no two bands of the same color are calibrated the same — flagged
# "approximate" wherever shown, never treated as a measured value.
BAND_TAG_KG = {"light": 10.0, "medium": 20.0, "heavy": 35.0}


@dataclass(frozen=True)
class LoadResult:
    effective_load_kg: Optional[float]
    is_estimated: bool
    note: Optional[str] = None


def barbell_load(plate_load_kg: float, bar_weight_kg: float = DEFAULT_BARBELL_KG) -> LoadResult:
    return LoadResult(plate_load_kg + bar_weight_kg, False)


def smith_load(plate_load_kg: float, bar_weight_kg: Optional[float]) -> LoadResult:
    if bar_weight_kg is None:
        return LoadResult(
            plate_load_kg + DEFAULT_UNKNOWN_SMITH_BAR_KG,
            True,
            "Smith bar weight not set for this gym — using a rough default; enter it once in gym setup for an accurate number.",
        )
    return LoadResult(plate_load_kg + bar_weight_kg, False)


def dumbbell_or_kettlebell_load(per_hand_kg: float, bilateral: bool) -> LoadResult:
    return LoadResult(per_hand_kg * 2.0 if bilateral else per_hand_kg, False)


def machine_plate_load(load_kg: float, base_weight_kg: float = 0.0) -> LoadResult:
    return LoadResult(load_kg + base_weight_kg, False)


def selectorized_load(stack_number: float, kg_per_increment: float = 1.0, base_weight_kg: float = 0.0) -> LoadResult:
    return LoadResult(stack_number * kg_per_increment + base_weight_kg, False)


def cable_load(stack_load_kg: float, pulley_multiplier: float = 1.0) -> LoadResult:
    return LoadResult(stack_load_kg * pulley_multiplier, False)


def bodyweight_load(bodyweight_kg: Optional[float]) -> LoadResult:
    if bodyweight_kg is None:
        return LoadResult(None, True, "No bodyweight on file yet — log a weight in Body to get an effective load.")
    return LoadResult(bodyweight_kg, False)


def weighted_bodyweight_load(bodyweight_kg: Optional[float], added_weight_kg: float) -> LoadResult:
    if bodyweight_kg is None:
        return LoadResult(added_weight_kg, True, "No bodyweight on file — this is added weight only, not total load.")
    return LoadResult(bodyweight_kg + added_weight_kg, False)


def assisted_bodyweight_load(bodyweight_kg: Optional[float], assistance_kg: float) -> LoadResult:
    if bodyweight_kg is None:
        return LoadResult(None, True, "No bodyweight on file yet — log a weight in Body to get an effective load.")
    return LoadResult(max(0.0, bodyweight_kg - assistance_kg), False)


def band_load(tag: str) -> LoadResult:
    kg = BAND_TAG_KG.get(tag)
    if kg is None:
        return LoadResult(None, True, f"Unknown band tag {tag!r}.")
    return LoadResult(kg, True, "Band resistance is an approximate tag-based estimate, not a measured value.")


def plates_per_side(total_plate_load_kg: float, available_kg: Optional[list[float]] = None) -> tuple[list[float], float]:
    """Greedy plate calculator. `total_plate_load_kg` is the plates only (both sides combined
    — i.e. the same `plate_load_kg` `barbell_load`/`smith_load` take), matching what's
    actually loaded on the bar; returns the plates for *one* side and any un-representable
    remainder (e.g. an odd 1kg request with no plate that small)."""
    available_kg = sorted(available_kg or DEFAULT_PLATES_KG, reverse=True)
    per_side = max(0.0, total_plate_load_kg) / 2.0
    plates: list[float] = []
    remaining = per_side
    for plate in available_kg:
        while remaining + 1e-6 >= plate:
            plates.append(plate)
            remaining -= plate
    return plates, max(0.0, round(remaining, 3))
