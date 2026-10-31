from __future__ import annotations

import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlmodel import Session, select

from catch.analytics.classify import (
    CONCEPT2_ON_WATER_TYPES,
    CONCEPT2_OTHER_TYPES,
    GARMIN_ERG_TYPES,
    GARMIN_ON_WATER_TYPES,
    workout_category,
)
from catch.analytics.zones import training_zones, zone_for_hr
from catch.api.deps import as_utc, get_db, require_auth
from catch.core.models import Activity, DailyScore, Note
from catch.core.settings_store import get_settings

router = APIRouter(dependencies=[Depends(require_auth)])

_PAGE_SIZE_DEFAULT = 30
_PAGE_SIZE_MAX = 100


def _category_filter(category: str):
    if category == "erg":
        return or_(
            (Activity.source == "concept2") & ~Activity.type.in_(CONCEPT2_ON_WATER_TYPES | CONCEPT2_OTHER_TYPES),
            (Activity.source == "garmin") & Activity.type.in_(GARMIN_ERG_TYPES),
        )
    if category == "on_water":
        return or_(
            (Activity.source == "concept2") & Activity.type.in_(CONCEPT2_ON_WATER_TYPES),
            (Activity.source == "garmin") & Activity.type.in_(GARMIN_ON_WATER_TYPES),
        )
    if category == "other":
        return or_(
            (Activity.source == "concept2") & Activity.type.in_(CONCEPT2_OTHER_TYPES),
            (Activity.source == "garmin") & ~Activity.type.in_(GARMIN_ERG_TYPES | GARMIN_ON_WATER_TYPES),
        )
    raise HTTPException(status_code=400, detail=f"Unknown category '{category}'. Allowed: erg, on_water, other")


def _not_linked_garmin_duplicate():
    # A linked Garmin<->Concept2 pair is one physical session; keep only the Concept2 side
    # (source of truth for erg metrics), matching catch/sync/scoring.py's _day_activities.
    return ~((Activity.source == "garmin") & Activity.linked_activity_id.is_not(None))


def _parse_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    try:
        start_iso, id_str = cursor.rsplit("_", 1)
        return as_utc(datetime.fromisoformat(start_iso)), int(id_str)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


def _activity_local_date(activity: Activity) -> date | None:
    # Matches catch/sync/scoring.py's day-bucketing: a naive datetime's .astimezone() assumes
    # the system's own local timezone, which is what date.today()/Garmin's calendarDate/
    # notes.date all use. Only correct if the Pi's system timezone matches the athlete's own.
    if activity.start is None:
        return None
    return activity.start.astimezone().date()


def _activity_strain(db: Session, activity: Activity, strain_by_date: dict[date, dict] | None = None) -> dict | None:
    """Per-activity strain was already computed and cached by catch/sync/scoring.py's
    day_strain (each per-activity component carries its own activity_id) — read it back
    instead of recomputing, so this stays a cheap lookup even for a long activity list."""
    local_date = _activity_local_date(activity)
    if local_date is None:
        return None
    if strain_by_date is not None:
        day_strain = strain_by_date.get(local_date)
    else:
        row = db.get(DailyScore, local_date)
        day_strain = json.loads(row.strain_json) if (row and row.strain_json) else None
    if not day_strain:
        return None
    for component in day_strain.get("components", []):
        if component.get("activity_id") == activity.id:
            return component
    return None


@router.get("/api/activities")
def list_activities(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    category: str | None = Query(None, description="erg | on_water | other"),
    limit: int = Query(_PAGE_SIZE_DEFAULT, ge=1, le=_PAGE_SIZE_MAX),
    cursor: str | None = Query(None, description="opaque, from the previous page's next_cursor"),
    db: Session = Depends(get_db),
):
    from_, to = as_utc(from_), as_utc(to)
    stmt = select(Activity).where(_not_linked_garmin_duplicate())
    if from_:
        stmt = stmt.where(Activity.start >= from_)
    if to:
        stmt = stmt.where(Activity.start <= to)
    if category:
        stmt = stmt.where(_category_filter(category))

    cursor_parsed = _parse_cursor(cursor)
    if cursor_parsed:
        cursor_start, cursor_id = cursor_parsed
        # Keyset pagination, not OFFSET: a background sync inserting rows between page
        # fetches would otherwise shift offsets and produce skipped or duplicated rows.
        stmt = stmt.where(
            or_(Activity.start < cursor_start, (Activity.start == cursor_start) & (Activity.id < cursor_id))
        )
    stmt = stmt.order_by(Activity.start.desc(), Activity.id.desc()).limit(limit)
    rows = db.exec(stmt).all()

    dates = {d for d in (_activity_local_date(a) for a in rows) if d is not None}
    score_rows = db.exec(select(DailyScore).where(DailyScore.date.in_(dates))).all() if dates else []
    strain_by_date = {r.date: json.loads(r.strain_json) for r in score_rows if r.strain_json}

    items = []
    for a in rows:
        data = a.model_dump(exclude={"raw_json", "intervals_json"})
        data["category"] = workout_category(a.source, a.type)
        data["strain"] = _activity_strain(db, a, strain_by_date)
        items.append(data)

    next_cursor = None
    if len(rows) == limit and rows[-1].start is not None:
        next_cursor = f"{rows[-1].start.isoformat()}_{rows[-1].id}"
    return {"items": items, "next_cursor": next_cursor}


@router.get("/api/activities/{activity_id}")
def get_activity(activity_id: int, db: Session = Depends(get_db)):
    activity = db.get(Activity, activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    settings = get_settings(db)
    local_date = _activity_local_date(activity)
    note = db.exec(select(Note).where(Note.date == local_date)).first() if local_date else None

    data = activity.model_dump(exclude={"raw_json", "intervals_json"})
    data["intervals"] = json.loads(activity.intervals_json) if activity.intervals_json else None
    data["category"] = workout_category(activity.source, activity.type)
    data["local_date"] = local_date
    data["strain"] = _activity_strain(db, activity)
    data["zones"] = training_zones(max_hr=settings.get("max_hr"), settings=settings)
    data["hr_zone"] = zone_for_hr(activity.avg_hr, settings.get("max_hr"), settings)
    data["note"] = note
    return data
