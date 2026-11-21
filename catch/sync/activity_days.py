"""Session 32 (docs/time.md): "the workouts on these local days", read by each workout's own stamped day — one query, bounded to
the days asked for (never the whole history). A canonical written before the stamp existed (local_date NULL) is caught by a UTC
window one day wider on each side and placed by catch.core.localtime.day_of."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import or_
from sqlmodel import Session, select

from catch.core import localtime
from catch.core.models import CanonicalActivity


def canonical_in_days(session: Session, first: date, last: date, *extra_where) -> list[CanonicalActivity]:
    lo_utc, _ = localtime.day_range(session, first - timedelta(days=1))
    _, hi_utc = localtime.day_range(session, last + timedelta(days=1))
    rows = session.exec(
        select(CanonicalActivity)
        .where(
            or_(
                (CanonicalActivity.local_date >= first) & (CanonicalActivity.local_date <= last),
                CanonicalActivity.local_date.is_(None) & (CanonicalActivity.start >= lo_utc) & (CanonicalActivity.start < hi_utc),
            ),
            *extra_where,
        )
        .order_by(CanonicalActivity.start)
    ).all()
    out = []
    for c in rows:
        day = localtime.day_of(session, c)
        if day is not None and first <= day <= last:
            out.append(c)
    return out
