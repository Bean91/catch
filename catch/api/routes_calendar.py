from __future__ import annotations

from datetime import date as date_
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.sync import planning as sp

router = APIRouter(dependencies=[Depends(require_auth)])

OWNER = sp.OWNER_ID


def _guard(fn):
    try:
        return fn()
    except sp.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except sp.PlanningError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# --- Calendar reads ---------------------------------------------------------------------------


@router.get("/api/calendar")
def get_calendar(from_: date_ = Query(..., alias="from"), to: date_ = Query(...), db: Session = Depends(get_db)):
    return _guard(lambda: sp.build_calendar(db, OWNER, from_, to))


@router.get("/api/calendar/week-summary")
def get_week_summary(week_start: date_ | None = Query(None), db: Session = Depends(get_db)):
    return _guard(lambda: sp.build_week_summary(db, OWNER, week_start or sp.today()))


@router.get("/api/calendar/phase")
def get_phase_on(on: date_ | None = Query(None, alias="date"), db: Session = Depends(get_db)):
    day = on or sp.today()
    phase = sp.phase_on(db, OWNER, day)
    from catch.core.settings_store import get_settings

    return {
        "date": day,
        "phase": sp.phase_dict(phase, db) if phase else None,
        "targets": sp.weekly_targets(db, phase, get_settings(db)),
    }


# --- Planned workouts -------------------------------------------------------------------------


class RepeatRequest(BaseModel):
    every: str = "weekly"
    weekdays: list[int] | None = None
    interval_weeks: int = 1
    until: date_ | None = None
    count: int | None = None


class PlannedCreate(BaseModel):
    date: date_
    session_type: str
    title: str | None = None
    start_time: str | None = None
    sport_family: str | None = None
    duration_min: float | None = None
    distance_m: float | None = None
    target_zone: str | None = None
    intensity_note: str | None = None
    description: str | None = None
    structure: list[dict] | None = None
    event_id: int | None = None
    notes: str | None = None
    coach_feedback: str | None = None
    repeat: RepeatRequest | None = None


@router.post("/api/planned")
def create_planned(body: PlannedCreate, db: Session = Depends(get_db)):
    data = body.model_dump(exclude={"repeat"}, exclude_none=True)
    repeat = body.repeat.model_dump(exclude_none=True) if body.repeat else None
    rows = _guard(lambda: sp.create_planned(db, OWNER, data, repeat))
    return {"planned": [sp.planned_dict(r) for r in rows]}


@router.patch("/api/planned/{planned_id}")
def update_planned(planned_id: int, body: dict[str, Any] = Body(...), scope: str = Query("this"), db: Session = Depends(get_db)):
    rows = _guard(lambda: sp.update_planned(db, OWNER, planned_id, body, scope))
    return {"planned": [sp.planned_dict(r) for r in rows]}


class MoveRequest(BaseModel):
    date: date_


@router.post("/api/planned/{planned_id}/move")
def move_planned(planned_id: int, body: MoveRequest, db: Session = Depends(get_db)):
    return sp.planned_dict(_guard(lambda: sp.move_planned(db, OWNER, planned_id, body.date)))


class LinkRequest(BaseModel):
    canonical_id: int


@router.post("/api/planned/{planned_id}/link")
def link_planned(planned_id: int, body: LinkRequest, db: Session = Depends(get_db)):
    return sp.planned_dict(_guard(lambda: sp.link_planned(db, OWNER, planned_id, body.canonical_id)))


@router.post("/api/planned/{planned_id}/unlink")
def unlink_planned(planned_id: int, db: Session = Depends(get_db)):
    return sp.planned_dict(_guard(lambda: sp.unlink_planned(db, OWNER, planned_id)))


@router.post("/api/planned/{planned_id}/decline")
def decline_suggestion(planned_id: int, body: LinkRequest, db: Session = Depends(get_db)):
    _guard(lambda: sp.decline_suggestion(db, OWNER, planned_id, body.canonical_id))
    return {"ok": True}


@router.post("/api/planned/{planned_id}/skip")
def skip_planned(planned_id: int, db: Session = Depends(get_db)):
    return sp.planned_dict(_guard(lambda: sp.set_skipped(db, OWNER, planned_id, True)))


@router.post("/api/planned/{planned_id}/unskip")
def unskip_planned(planned_id: int, db: Session = Depends(get_db)):
    return sp.planned_dict(_guard(lambda: sp.set_skipped(db, OWNER, planned_id, False)))


@router.delete("/api/planned/{planned_id}")
def delete_planned(planned_id: int, scope: str = Query("this"), db: Session = Depends(get_db)):
    return {"deleted": _guard(lambda: sp.delete_planned(db, OWNER, planned_id, scope))}


@router.get("/api/planned/{planned_id}")
def get_planned(planned_id: int, db: Session = Depends(get_db)):
    return sp.planned_dict(_guard(lambda: sp.get_planned(db, OWNER, planned_id)))


# --- Events -----------------------------------------------------------------------------------


class EventCreate(BaseModel):
    name: str
    date: date_
    type: str
    distance: str | None = None
    distance_m: float | None = None
    boat_class: str | None = None
    priority: str | None = None
    goal_time: str | None = None
    result: str | None = None
    location: str | None = None
    goals: str | None = None
    notes: str | None = None


@router.get("/api/events")
def list_events(
    from_: date_ | None = Query(None, alias="from"), to: date_ | None = Query(None), db: Session = Depends(get_db)
):
    today = sp.today()
    return {"events": [sp.event_dict(e, today) for e in sp.list_events(db, OWNER, from_, to)]}


# Registered before `{event_id}` so "upcoming" is never parsed as an id.
@router.get("/api/events/upcoming")
def upcoming_events(limit: int = Query(5, ge=1, le=50), db: Session = Depends(get_db)):
    return {"events": sp.upcoming_events(db, OWNER, limit)}


@router.post("/api/events")
def create_event(body: EventCreate, db: Session = Depends(get_db)):
    event = _guard(lambda: sp.create_event(db, OWNER, body.model_dump(exclude_none=True)))
    return sp.event_dict(event)


@router.get("/api/events/{event_id}")
def get_event(event_id: int, db: Session = Depends(get_db)):
    return _guard(lambda: sp.event_overview(db, OWNER, event_id))


@router.patch("/api/events/{event_id}")
def update_event(event_id: int, body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    return sp.event_dict(_guard(lambda: sp.update_event(db, OWNER, event_id, body)))


@router.delete("/api/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    _guard(lambda: sp.delete_event(db, OWNER, event_id))
    return {"ok": True}


@router.get("/api/events/{event_id}/projection")
def event_projection(event_id: int, db: Session = Depends(get_db)):
    return _guard(lambda: sp.event_projection(db, OWNER, event_id))


# --- Phases -----------------------------------------------------------------------------------


class PhaseCreate(BaseModel):
    kind: str
    name: str
    start_date: date_
    end_date: date_
    goals: str | None = None
    target_minutes_per_week: float | None = None
    target_sessions_per_week: float | None = None
    target_strength_sessions_per_week: float | None = None
    target_zone_pct: dict[str, dict[str, float]] | None = None
    event_id: int | None = None


class ApproveRequest(BaseModel):
    approved_by: str | None = None
    note: str | None = None


@router.get("/api/phases")
def list_phases(db: Session = Depends(get_db)):
    return {"phases": [sp.phase_dict(p, db) for p in sp.list_phases(db, OWNER)]}


@router.post("/api/phases")
def create_phase(body: PhaseCreate, db: Session = Depends(get_db)):
    return sp.phase_dict(_guard(lambda: sp.create_phase(db, OWNER, body.model_dump(exclude_none=True))), db)


@router.patch("/api/phases/{phase_id}")
def update_phase(phase_id: int, body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    return sp.phase_dict(_guard(lambda: sp.update_phase(db, OWNER, phase_id, body)), db)


@router.delete("/api/phases/{phase_id}")
def delete_phase(phase_id: int, db: Session = Depends(get_db)):
    _guard(lambda: sp.delete_phase(db, OWNER, phase_id))
    return {"ok": True}


@router.post("/api/phases/{phase_id}/approve")
def approve_phase(phase_id: int, body: ApproveRequest = Body(default_factory=ApproveRequest), db: Session = Depends(get_db)):
    return sp.phase_dict(_guard(lambda: sp.approve_phase(db, OWNER, phase_id, body.approved_by, body.note)), db)


@router.post("/api/phases/{phase_id}/unapprove")
def unapprove_phase(phase_id: int, db: Session = Depends(get_db)):
    return sp.phase_dict(_guard(lambda: sp.unapprove_phase(db, OWNER, phase_id)), db)
