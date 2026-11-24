"""Session 36 follow-up: the athlete's planned sessions and events as an .ics file (format rules in catch/analytics/ics.py).

A download, not a subscription: a calendar app can't send this app's sign-in, and a feed URL would need a new kind of unauthenticated
token. A planned session's "HH:MM" start is the athlete's local time on that day, turned into UTC with the zone Catch uses for that
day (catch/core/localtime.py); without a start time it is an all-day entry. Skipped sessions are written as cancelled."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from catch.analytics import ics
from catch.core import localtime
from catch.core.models import Event, PlannedWorkout

MAX_RANGE_DAYS = 2 * 366


def clamp(session: Session, start: Optional[date], end: Optional[date]) -> tuple[date, date]:
    today = localtime.today(session)
    start = start or today - timedelta(days=30)
    end = end or today + timedelta(days=365)
    if start > end:
        start, end = end, start
    if (end - start).days > MAX_RANGE_DAYS:
        end = start + timedelta(days=MAX_RANGE_DAYS)
    return start, end


def _start(session: Session, p: PlannedWorkout) -> Optional[datetime]:
    if not p.start_time:
        return None
    try:
        hh, mm = (int(x) for x in p.start_time.split(":")[:2])
        return datetime.combine(p.date, time(hh, mm), tzinfo=localtime.zone_for_day(session, p.date))
    except (ValueError, TypeError):
        return None


def _planned_text(p: PlannedWorkout) -> str:
    bits = []
    if p.duration_min:
        bits.append(f"{round(p.duration_min)} min")
    if p.distance_m:
        bits.append(f"{round(p.distance_m):,} m")
    if p.target_zone:
        bits.append(f"zone {p.target_zone}")
    parts = [" · ".join(bits)] if bits else []
    for extra in (p.intensity_note, p.description):
        if extra:
            parts.append(extra)
    parts.append("A plan, not a completed workout.")
    return "\n".join(parts)


def _event_text(e: Event) -> str:
    parts = [" · ".join(x for x in (e.type.replace("_", " "), f"priority {e.priority}" if e.priority else None, e.distance) if x)]
    for extra in (e.goal_time and f"Goal: {e.goal_time}", e.goals, e.notes):
        if extra:
            parts.append(extra)
    return "\n".join(p for p in parts if p)


def build(session: Session, owner_id: str, start: date, end: date, now: Optional[datetime] = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    # A keyed suffix keeps UIDs from two accounts apart without putting an account id in the file.
    suffix = hashlib.sha256(f"catch-ics:{owner_id}".encode()).hexdigest()[:12]
    out: list[list[str]] = []
    plans = session.exec(select(PlannedWorkout).where(PlannedWorkout.date >= start, PlannedWorkout.date <= end).order_by(PlannedWorkout.date, PlannedWorkout.id)).all()
    for p in plans:
        out.append(ics.vevent(
            uid=f"planned-{p.id}-{suffix}@catch", stamp=stamp, summary=p.title, day=p.date, start=_start(session, p), minutes=p.duration_min,
            description=_planned_text(p), cancelled=p.status == "skipped", categories="Training plan",
        ))
    events = session.exec(select(Event).where(Event.date >= start, Event.date <= end).order_by(Event.date, Event.id)).all()
    for e in events:
        out.append(ics.vevent(
            uid=f"event-{e.id}-{suffix}@catch", stamp=stamp, summary=e.name, day=e.date, description=_event_text(e) or None,
            location=e.location, cancelled=e.participation in ("withdrawn", "did_not_start"), categories="Event",
        ))
    return ics.calendar(out)
