from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from catch.api.deps import as_utc, get_db, require_auth
from catch.core.models import BodyComp

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/body")
def list_body_comp(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    db: Session = Depends(get_db),
):
    from_, to = as_utc(from_), as_utc(to)
    stmt = select(BodyComp)
    if from_:
        stmt = stmt.where(BodyComp.ts >= from_)
    if to:
        stmt = stmt.where(BodyComp.ts <= to)
    stmt = stmt.order_by(BodyComp.ts)
    return db.exec(stmt).all()
