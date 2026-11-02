from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.sync.body_comp import resolve_daily
from catch.sync.upsert import upsert_body_comp

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/body")
def list_body_comp(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    db: Session = Depends(get_db),
):
    """One row per calendar day (task Part D.2) — the priority-resolved weight/fat%/muscle
    mass across every source that reported one that day, never averaged, each tagged with
    the source it actually came from (`resolve_daily`, catch/sync/body_comp.py)."""
    return resolve_daily(db, from_, to)


class ManualWeightRequest(BaseModel):
    date: date
    weight_kg: float


@router.post("/api/body/manual")
def post_manual_weight(body: ManualWeightRequest = Body(...), db: Session = Depends(get_db)):
    """Part D.3 — the app works with no scale at all: a manually entered weight, always the
    last-resort source regardless of `body_comp_priority`'s configured order."""
    ts = datetime.combine(body.date, datetime.min.time(), tzinfo=timezone.utc)
    row = upsert_body_comp(db, source="manual", external_id=body.date.isoformat(), ts=ts, weight_kg=body.weight_kg)

    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    return row
