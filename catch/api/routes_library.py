from __future__ import annotations

from datetime import date as date_
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core.principal import OWNER_ID
from catch.sync import planning as sp
from catch.sync import workout_library as lib

# Cookie-only: a device token (including a coach's) never reaches these routes.
router = APIRouter(dependencies=[Depends(require_auth)])

OWNER = OWNER_ID


def _guard(fn):
    try:
        return fn()
    except lib.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (lib.LibraryError, sp.PlanningError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/api/library/templates")
def list_templates(
    q: str | None = Query(None),
    workout_type: str | None = Query(None),
    difficulty: str | None = Query(None),
    tag: str | None = Query(None),
    scope: str = Query("mine", pattern="^(mine|examples|all|archived)$"),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    rows = lib.search_templates(
        db, OWNER, q=q, workout_type=workout_type, difficulty=difficulty, tags=[tag] if tag else None,
        include_examples=scope in ("examples", "all"), only_examples=scope == "examples",
        include_archived=scope == "archived", limit=limit,
    )
    if scope == "archived":
        rows = [r for r in rows if r.archived_at is not None]
    return {"templates": [lib.template_dict(r) for r in rows]}


@router.post("/api/library/templates/preview")
def preview_template(body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    return lib.preview_template(db, body)


@router.post("/api/library/templates")
def create_template(body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    return lib.template_dict(_guard(lambda: lib.create_template(db, OWNER, body)))


@router.get("/api/library/templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db)):
    return lib.template_dict(_guard(lambda: lib.get_template(db, OWNER, template_id)))


@router.patch("/api/library/templates/{template_id}")
def update_template(template_id: int, body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    return lib.template_dict(_guard(lambda: lib.update_template(db, OWNER, template_id, body)))


class DuplicateRequest(BaseModel):
    name: str | None = None


@router.post("/api/library/templates/{template_id}/duplicate")
def duplicate_template(template_id: int, body: DuplicateRequest = Body(default=DuplicateRequest()), db: Session = Depends(get_db)):
    return lib.template_dict(_guard(lambda: lib.duplicate_template(db, OWNER, template_id, body.name)))


@router.post("/api/library/templates/{template_id}/archive")
def archive_template(template_id: int, db: Session = Depends(get_db)):
    return lib.template_dict(_guard(lambda: lib.set_archived(db, OWNER, template_id, True)))


@router.post("/api/library/templates/{template_id}/unarchive")
def unarchive_template(template_id: int, db: Session = Depends(get_db)):
    return lib.template_dict(_guard(lambda: lib.set_archived(db, OWNER, template_id, False)))


class RepeatRequest(BaseModel):
    every: str = "weekly"
    weekdays: list[int] | None = None
    interval_weeks: int = 1
    until: date_ | None = None
    count: int | None = None


class ScheduleRequest(BaseModel):
    date: date_
    start_time: str | None = None
    event_id: int | None = None
    repeat: RepeatRequest | None = None


@router.post("/api/library/templates/{template_id}/schedule")
def schedule_template(template_id: int, body: ScheduleRequest, db: Session = Depends(get_db)):
    repeat = body.repeat.model_dump(exclude_none=True) if body.repeat else None
    rows = _guard(lambda: lib.schedule_template(db, OWNER, template_id, body.date, start_time=body.start_time, repeat=repeat, event_id=body.event_id))
    return {"planned": [sp.planned_dict(r) for r in rows]}
