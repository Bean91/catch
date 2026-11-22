from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from catch.analytics.bodyweight import plausible_body_mass
from catch.analytics.units import body_mass_kg
from catch.api.deps import get_db, require_auth
from catch.core import localtime
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
    # Session 34: `weight` + `unit` ("kg" | "lb"), converted to kilograms here — the one place a pound value can enter Catch. The
    # older `weight_kg` field still works.
    weight_kg: float | None = None
    weight: float | None = None
    unit: str = "kg"


@router.post("/api/body/manual")
def post_manual_weight(body: ManualWeightRequest = Body(...), db: Session = Depends(get_db)):
    """Part D.3 — the app works with no scale at all: a manually entered weight, always the
    last-resort source regardless of `body_comp_priority`'s configured order."""
    try:
        kg = body.weight_kg if body.weight is None else body_mass_kg(body.weight, body.unit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if not plausible_body_mass(kg):
        raise HTTPException(status_code=422, detail="Enter a body weight between 25 and 300 kg (55–660 lb).")
    # Noon on that local day, in the athlete's zone (session 32): midnight UTC filed a weigh-in under the previous day west of UTC.
    tz = localtime.zone_for_day(db, body.date)
    ts = datetime(body.date.year, body.date.month, body.date.day, 12, tzinfo=tz).astimezone(timezone.utc)
    row = upsert_body_comp(db, source="manual", external_id=body.date.isoformat(), ts=ts, weight_kg=kg)

    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    return row
