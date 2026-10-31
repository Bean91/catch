from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from catch.api.deps import as_utc, get_db, require_auth
from catch.core.models import Activity

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/activities")
def list_activities(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    db: Session = Depends(get_db),
):
    from_, to = as_utc(from_), as_utc(to)
    stmt = select(Activity)
    if from_:
        stmt = stmt.where(Activity.start >= from_)
    if to:
        stmt = stmt.where(Activity.start <= to)
    stmt = stmt.order_by(Activity.start.desc())
    return db.exec(stmt).all()


@router.get("/api/activities/{activity_id}")
def get_activity(activity_id: int, db: Session = Depends(get_db)):
    activity = db.get(Activity, activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    return activity
