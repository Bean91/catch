from __future__ import annotations

"""Session 34 (docs/analytics.md §34): which body mass belongs to a performance on a given day. Pure; the DB side is
sync/body_comp.py.

Rule: the latest plausible weigh-in on or before the performance's local day, at most BEFORE_DAYS old; otherwise the earliest one within
AFTER_DAYS after it (someone who only weighs in now and then still gets their next reading); otherwise none — never today's weight
by default and never an invented one."""

import math
from bisect import bisect_left, bisect_right
from datetime import date
from typing import Optional, Sequence

BEFORE_DAYS = 30
AFTER_DAYS = 7
# A scale's misread (a child stepping on, a bag) is not this athlete's body mass.
PLAUSIBLE_KG = (25.0, 300.0)


def plausible_body_mass(kg: Optional[float]) -> bool:
    return kg is not None and isinstance(kg, (int, float)) and math.isfinite(kg) and PLAUSIBLE_KG[0] <= kg <= PLAUSIBLE_KG[1]


def weight_for_day(days: Sequence[date], weights: Sequence[float], target: date) -> Optional[tuple[float, date]]:
    """(kg, the weigh-in's day) for `target`, from `days` sorted ascending with `weights` aligned and already plausible."""
    if not days or target is None:
        return None
    i = bisect_right(days, target) - 1
    if i >= 0 and (target - days[i]).days <= BEFORE_DAYS:
        return weights[i], days[i]
    j = bisect_left(days, target)
    if j < len(days) and (days[j] - target).days <= AFTER_DAYS:
        return weights[j], days[j]
    return None
