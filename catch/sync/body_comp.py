from __future__ import annotations

"""Part D — one canonical daily body-composition measurement from however many scales
reported one, with a per-metric source priority (Settings, default Withings first, Garmin
second; a user-entered "manual" reading is always the last resort regardless of that order).
Never averages two scales; always says which source a value came from."""

from datetime import date as date_
from typing import Optional

from sqlmodel import Session, select

from catch.core.models import BodyComp
from catch.core.settings_store import get_settings

_METRIC_COLUMNS = {"weight": "weight_kg", "fat_pct": "fat_pct", "muscle_kg": "muscle_kg"}


def resolve_daily(session: Session, from_: Optional[date_] = None, to: Optional[date_] = None) -> list[dict]:
    rows = session.exec(select(BodyComp)).all()
    by_day: dict[date_, list[BodyComp]] = {}
    for r in rows:
        if r.ts is None:
            continue
        day = r.ts.astimezone().date()
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


def nearest_resolved_weight_kg(session: Session, when) -> Optional[float]:
    """Nearest *day* with a resolved weight (priority-aware — see resolve_daily), not just
    whichever raw BodyComp row happens to sit closest in wall-clock time; replaces the old
    cross-source-blind nearest-row lookup `_nearest_weight_kg` used before session 8/12."""
    if when is None:
        return None
    daily = [d for d in resolve_daily(session) if d["weight"] is not None]
    if not daily:
        return None
    target_day = when.astimezone().date()
    closest = min(daily, key=lambda d: abs((d["date"] - target_day).days))
    return closest["weight"]
