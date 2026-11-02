from __future__ import annotations

from datetime import date as date_, datetime, timezone
from typing import Any

from sqlmodel import Session, select

from catch.analytics.matching import sport_family as _sport_family
from catch.core.models import Activity, BodyComp, CanonicalActivity, DailyWellness, Note, Stroke


def upsert_daily_wellness(session: Session, day: date_, **fields: Any) -> DailyWellness:
    """Merge-upsert: only overwrites columns explicitly passed (not None), since several
    Garmin calls each fill different columns of the same day."""
    row = session.get(DailyWellness, day)
    if row is None:
        row = DailyWellness(date=day)
        session.add(row)
    for key, value in fields.items():
        if value is not None:
            setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(row)
    return row


def upsert_activity(session: Session, source: str, external_id: str, **fields: Any) -> Activity:
    row = session.exec(
        select(Activity).where(Activity.source == source, Activity.external_id == external_id)
    ).first()
    is_new = row is None
    if row is None:
        row = Activity(source=source, external_id=external_id)
        session.add(row)
    for key, value in fields.items():
        if value is not None:
            setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)
    if row.sport_family is None:
        row.sport_family = _sport_family(row.source, row.type)
    session.add(row)
    session.commit()
    session.refresh(row)

    if is_new and row.canonical_id is None:
        # Every source record gets its own standalone canonical immediately (session 8/12 —
        # see PLAN.md) so every downstream reader can join on canonical_id unconditionally;
        # catch/sync/matching.py merges canonicals together when two records turn out to be
        # the same physical session.
        canonical = CanonicalActivity(sport_family=row.sport_family)
        session.add(canonical)
        session.flush()
        row.canonical_id = canonical.id
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def upsert_strokes(session: Session, activity_id: int, strokes: list[dict]) -> int:
    """Strokes have no natural per-row key, so a re-sync replaces a result's strokes wholesale
    instead of trying to diff individual rows."""
    existing = session.exec(select(Stroke).where(Stroke.activity_id == activity_id)).all()
    for row in existing:
        session.delete(row)
    for fields in strokes:
        session.add(Stroke(activity_id=activity_id, **fields))
    session.commit()
    return len(strokes)


def upsert_note(session: Session, day: date_, text: str, rpe: int | None) -> Note:
    """One note per calendar date — a later save on the same date overwrites it rather than
    appending another row, so strain's _note_rpe (catch/sync/scoring.py) always picks the one
    note that date, not an arbitrary one among several."""
    row = session.exec(select(Note).where(Note.date == day)).first()
    if row is None:
        row = Note(date=day, text=text, rpe=rpe)
        session.add(row)
    else:
        row.text = text
        row.rpe = rpe
    session.commit()
    session.refresh(row)
    return row


def upsert_body_comp(session: Session, source: str, external_id: str, **fields: Any) -> BodyComp:
    row = session.exec(
        select(BodyComp).where(BodyComp.source == source, BodyComp.external_id == external_id)
    ).first()
    if row is None:
        row = BodyComp(source=source, external_id=external_id, ts=fields.get("ts", datetime.now(timezone.utc)))
        session.add(row)
    for key, value in fields.items():
        if value is not None:
            setattr(row, key, value)
    session.commit()
    session.refresh(row)
    return row
