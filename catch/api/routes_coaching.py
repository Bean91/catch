from __future__ import annotations

from datetime import date as date_
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core.principal import ATHLETE, OWNER_ID
from catch.sync import coaching_notes as cn

# Cookie-only: the web UI is the athlete. A coach reaches this data through the tool endpoint
# with a coach-role token (catch/core/principal.py), where visibility is enforced per entry.
router = APIRouter(dependencies=[Depends(require_auth)])

OWNER = OWNER_ID


def _guard(fn):
    try:
        return fn()
    except cn.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except cn.Forbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except cn.CoachingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# --- Technique notes ---------------------------------------------------------------------------------


@router.get("/api/technique-notes")
def list_notes(
    workout_id: int | None = Query(None),
    piece_id: int | None = Query(None),
    date: date_ | None = Query(None),
    category: str | None = Query(None),
    from_: date_ | None = Query(None, alias="from"),
    to: date_ | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = _guard(lambda: cn.list_technique_notes(db, OWNER, ATHLETE, canonical_id=workout_id, piece_id=piece_id, note_date=date, category=category, date_from=from_, date_to=to, limit=limit))
    return {"notes": [cn.note_dict(db, r) for r in rows], "note": cn.CANNOT_RATE}


@router.post("/api/technique-notes")
def create_note(body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    return cn.note_dict(db, _guard(lambda: cn.create_technique_note(db, OWNER, ATHLETE, body)))


@router.patch("/api/technique-notes/{note_id}")
def update_note(note_id: int, body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    return cn.note_dict(db, _guard(lambda: cn.update_technique_note(db, OWNER, ATHLETE, note_id, body)))


@router.delete("/api/technique-notes/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db)):
    _guard(lambda: cn.delete_technique_note(db, OWNER, ATHLETE, note_id))
    return {"ok": True}


# --- Coach feedback ----------------------------------------------------------------------------------


@router.get("/api/coach-feedback")
def list_feedback(
    coach: str | None = Query(None),
    category: str | None = Query(None),
    from_: date_ | None = Query(None, alias="from"),
    to: date_ | None = Query(None),
    workout_id: int | None = Query(None),
    event_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows = _guard(lambda: cn.list_feedback(db, OWNER, ATHLETE, coach=coach, category=category, date_from=from_, date_to=to, canonical_id=workout_id, event_id=event_id, limit=limit, offset=offset))
    return {"feedback": [cn.feedback_dict(db, r, ATHLETE) for r in rows], "coaches": cn.list_coach_names(db, OWNER, ATHLETE)}


@router.get("/api/coach-feedback/coaches")
def list_coaches(db: Session = Depends(get_db)):
    return {"coaches": cn.list_coach_names(db, OWNER, ATHLETE)}


@router.post("/api/coach-feedback")
def create_feedback(body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    row = _guard(lambda: cn.create_feedback(db, OWNER, ATHLETE, body, via="web"))
    return cn.feedback_dict(db, row, ATHLETE)


@router.patch("/api/coach-feedback/{feedback_id}")
def update_feedback(feedback_id: int, body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    row = _guard(lambda: cn.update_feedback(db, OWNER, ATHLETE, feedback_id, body))
    return cn.feedback_dict(db, row, ATHLETE)


class ResponseRequest(BaseModel):
    response: str | None = None


@router.post("/api/coach-feedback/{feedback_id}/response")
def respond(feedback_id: int, body: ResponseRequest, db: Session = Depends(get_db)):
    row = _guard(lambda: cn.respond_to_feedback(db, OWNER, ATHLETE, feedback_id, body.response))
    return cn.feedback_dict(db, row, ATHLETE)


@router.get("/api/coach-feedback/{feedback_id}/history")
def history(feedback_id: int, db: Session = Depends(get_db)):
    return {"history": _guard(lambda: cn.feedback_history(db, OWNER, ATHLETE, feedback_id))}


@router.delete("/api/coach-feedback/{feedback_id}")
def delete_feedback(feedback_id: int, db: Session = Depends(get_db)):
    _guard(lambda: cn.delete_feedback(db, OWNER, ATHLETE, feedback_id))
    return {"ok": True}
