from __future__ import annotations

"""Part D — one canonical daily body-composition measurement from however many scales
reported one, with a per-metric source priority (Settings, default Withings first, Garmin
second; a user-entered "manual" reading is always the last resort regardless of that order).
Never averages two scales; always says which source a value came from."""

from bisect import bisect_left
from datetime import date as date_, timedelta
from typing import Optional

from sqlmodel import Session, select

from catch.core import localtime
from catch.core.models import BodyComp
from catch.core.settings_store import get_settings

_METRIC_COLUMNS = {"weight": "weight_kg", "fat_pct": "fat_pct", "muscle_kg": "muscle_kg"}
_MARGIN = timedelta(days=1)


def resolve_daily(session: Session, from_: Optional[date_] = None, to: Optional[date_] = None) -> list[dict]:
    stmt = select(BodyComp)
    # A ±1-day margin on the timestamp, then the exact local day below: a weigh-in's day is the zone it happened in.
    if from_:
        stmt = stmt.where(BodyComp.ts >= localtime.day_range(session, from_)[0] - _MARGIN)
    if to:
        stmt = stmt.where(BodyComp.ts < localtime.day_range(session, to)[1] + _MARGIN)
    rows = session.exec(stmt).all()
    by_day: dict[date_, list[BodyComp]] = {}
    for r in rows:
        if r.ts is None:
            continue
        day = localtime.day_of(session, r)
        by_day.setdefault(day, []).append(r)

    priority = get_settings(session)["body_comp_priority"]
    out = []
    for day in sorted(by_day):
        if from_ and day < from_:
            continue
        if to and day > to:
            continue
        day_rows = by_day[day]
        # If a source logged twice in one day (e.g. two manual entries), the latest timestamp
        # wins for that source — never averaged together.
        by_source: dict[str, BodyComp] = {}
        for r in sorted(day_rows, key=lambda r: r.ts):
            by_source[r.source] = r

        entry: dict = {"date": day}
        for metric, column in _METRIC_COLUMNS.items():
            # "manual" always sorts last, even if a user's custom priority put it earlier
            # (task Part D.3) — a real scale reading should never lose to a manual entry.
            order = [s for s in priority.get(metric, []) if s != "manual"] + ["manual"]
            value, source_used = None, None
            for src in order:
                row = by_source.get(src)
                v = getattr(row, column, None) if row else None
                if v is not None:
                    value, source_used = v, src
                    break
            entry[metric] = value
            entry[f"{metric}_source"] = source_used
        entry["bone_kg"] = next((r.bone_kg for r in day_rows if r.bone_kg is not None), None)
        entry["hydration_kg"] = next((r.hydration_kg for r in day_rows if r.hydration_kg is not None), None)
        entry["sources"] = sorted(by_source)
        out.append(entry)
    return out


class WeightLookup:
    """Every day's resolved weight, resolved once — for a request that needs the weight near many workouts (an erg-results
    list, a W/kg trend). Session 32: each lookup used to re-read and re-resolve the whole body-composition history."""

    def __init__(self, session: Session) -> None:
        self._session = session
        daily = [d for d in resolve_daily(session) if d["weight"] is not None]
        self._days = [d["date"] for d in daily]
        self._weights = [d["weight"] for d in daily]

    def nearest(self, when) -> Optional[float]:
        if when is None or not self._days:
            return None
        target = localtime.local_date_at(self._session, when)
        i = bisect_left(self._days, target)
        candidates = [j for j in (i - 1, i) if 0 <= j < len(self._days)]
        best = min(candidates, key=lambda j: (abs((self._days[j] - target).days), j))
        return self._weights[best]


def nearest_resolved_weight_kg(session: Session, when) -> Optional[float]:
    """Nearest *day* with a resolved weight (priority-aware — see resolve_daily), not just
    whichever raw BodyComp row happens to sit closest in wall-clock time."""
    return WeightLookup(session).nearest(when)
