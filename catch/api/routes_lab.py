"""Session 36: personal records and the Performance Lab. Plain `def` routes (database work never runs on the event loop — the session
33 pool deadlock), every read scoped to the signed-in owner by the tenant hooks."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.sync import performance_lab as lab
from catch.sync import records as rec

router = APIRouter(dependencies=[Depends(require_auth)])

_MODALITY = Query("rowing_erg", pattern="^(rowing_erg|bike)$")


@router.get("/api/records")
def get_records(
    modality: str = _MODALITY,
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    db: Session = Depends(get_db),
):
    return rec.records(db, modality, from_, to)


@router.get("/api/lab/progression")
def get_progression(modality: str = _MODALITY, from_: date | None = Query(None, alias="from"), to: date | None = Query(None), db: Session = Depends(get_db)):
    return lab.progression(db, modality, from_, to)


@router.get("/api/lab/hr-at-workload")
def get_hr_at_workload(from_: date | None = Query(None, alias="from"), to: date | None = Query(None), db: Session = Depends(get_db)):
    return lab.hr_at_workload(db, from_, to)


@router.get("/api/lab/split-by-rate")
def get_split_by_rate(from_: date | None = Query(None, alias="from"), to: date | None = Query(None), db: Session = Depends(get_db)):
    return lab.split_by_rate(db, from_, to)


@router.get("/api/lab/power-curve")
def get_power_curve(from_: date | None = Query(None, alias="from"), to: date | None = Query(None), db: Session = Depends(get_db)):
    return lab.power_curve(db, from_, to)


@router.get("/api/trends/load-history")
def get_load_history(weeks: int = Query(26, ge=5, le=104), db: Session = Depends(get_db)):
    from catch.sync.load_history import load_history

    return load_history(db, weeks)
