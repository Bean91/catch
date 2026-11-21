from __future__ import annotations

"""Session 33: the heart-rate zone basis (method, max HR, resting HR) for a day, read from the database — the one place the zone
code, workout detail, charts, pieces, trends and the coach get it from (pure rule: catch/analytics/hr_basis.py)."""

from datetime import date, timedelta
from typing import Optional

from sqlmodel import Session, select

from catch.analytics.hr_basis import STALE_DAYS, zone_resting_hr
from catch.analytics.zones import HrBasis, hr_basis
from catch.core import localtime
from catch.core.models import DailyWellness
from catch.core.settings_store import get_settings


class RhrLookup:
    """Resting-HR readings for a span of days, read once (one indexed range query), so a batch — a resolve of every workout, a
    12-week volume chart — doesn't query per workout."""

    def __init__(self, session: Session, first_day: date, last_day: date):
        rows = session.exec(
            select(DailyWellness.date, DailyWellness.resting_hr).where(
                DailyWellness.date >= first_day - timedelta(days=STALE_DAYS),
                DailyWellness.date < last_day,
                DailyWellness.resting_hr.is_not(None),
            )
        ).all()
        self.readings = [(d, v) for d, v in rows]

    def basis(self, day: date, settings: dict) -> HrBasis:
        chosen = zone_resting_hr(self.readings, day, settings.get("resting_hr"))
        return hr_basis(settings, chosen["resting_hr"], rhr_source=chosen["source"], rhr_window=chosen["window"], rhr_readings=chosen["readings"])


def basis_for_day(session: Session, day: Optional[date], settings: dict | None = None) -> HrBasis:
    settings = settings or get_settings(session)
    day = day or localtime.today(session)
    return RhrLookup(session, day, day).basis(day, settings)


def current_basis(session: Session, settings: dict | None = None) -> HrBasis:
    """The basis a workout recorded today would use — what Settings and the coach show."""
    return basis_for_day(session, localtime.today(session), settings)


def canonical_day(session: Session, canonical) -> Optional[date]:
    if canonical is None or canonical.start is None:
        return None
    return canonical.local_date or localtime.day_of(session, canonical)
