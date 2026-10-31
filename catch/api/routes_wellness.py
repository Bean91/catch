from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from catch.api.deps import get_db, require_auth
from catch.core.models import DailyWellness

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/wellness")
def list_wellness(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(DailyWellness)
    if from_:
        stmt = stmt.where(DailyWellness.date >= from_)
    if to:
        stmt = stmt.where(DailyWellness.date <= to)
    stmt = stmt.order_by(DailyWellness.date)
    return db.exec(stmt).all()
