from __future__ import annotations

from datetime import date as date_, datetime, timezone
from typing import Any

from sqlmodel import Session, select

from catch.core.models import Activity, BodyComp, DailyWellness


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
    if row is None:
        row = Activity(source=source, external_id=external_id)
        session.add(row)
    for key, value in fields.items():
        if value is not None:
            setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)
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
