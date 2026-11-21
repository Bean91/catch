from __future__ import annotations

"""Session 33: which resting heart rate a day's heart-rate-reserve zones use (docs/analytics.md §3). Pure — the readings come from
catch/sync/hr_basis.py.

Rule, in order:
1. the athlete's own resting HR setting, if entered;
2. the median of the resolved daily resting HR over the 14 days *before* the day (needs at least 4 readings) — a median over two
   weeks, so one odd night (a late meal, a bad sleep, the start of a cold) can't move every zone;
3. failing that, the most recent such 14-day median within 60 days, flagged stale;
4. otherwise none, and the zones fall back to % of max HR with that reason stated.
The day's own reading is excluded: it usually arrives that morning, and a workout's zones shouldn't change with it."""

from datetime import date, timedelta
from statistics import median
from typing import Optional

WINDOW_DAYS = 14
MIN_READINGS = 4
STALE_DAYS = 60
PLAUSIBLE = (30.0, 100.0)


def _valid(readings: list[tuple[date, float]]) -> list[tuple[date, float]]:
    return sorted((d, float(v)) for d, v in readings if v is not None and PLAUSIBLE[0] <= v <= PLAUSIBLE[1])


def zone_resting_hr(readings: list[tuple[date, float]], day: date, override: Optional[float] = None) -> dict:
    """{resting_hr, source, window, readings}. `readings` may span any range; only the 60 days before `day` are used."""
    if override is not None:
        return {"resting_hr": float(override), "source": "setting", "window": None, "readings": 0}
    usable = [(d, v) for d, v in _valid(readings) if day - timedelta(days=STALE_DAYS) <= d < day]
    recent = [(d, v) for d, v in usable if d >= day - timedelta(days=WINDOW_DAYS)]
    if len(recent) >= MIN_READINGS:
        return {"resting_hr": round(median(v for _, v in recent), 1), "source": "measured", "window": [recent[0][0].isoformat(), recent[-1][0].isoformat()], "readings": len(recent)}
    if usable:
        last = usable[-1][0]
        older = [(d, v) for d, v in usable if d > last - timedelta(days=WINDOW_DAYS)]
        if len(older) >= MIN_READINGS:
            return {"resting_hr": round(median(v for _, v in older), 1), "source": "measured_stale", "window": [older[0][0].isoformat(), older[-1][0].isoformat()], "readings": len(older)}
    return {"resting_hr": None, "source": "none", "window": None, "readings": 0}
