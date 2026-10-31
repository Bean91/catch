from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from catch.api.deps import get_db, require_auth
from catch.core.models import Note
from catch.sync.upsert import upsert_note

router = APIRouter(dependencies=[Depends(require_auth)])


class NoteRequest(BaseModel):
    date: date
    text: str
    rpe: int | None = None


@router.get("/api/notes")
def get_note(date: date, db: Session = Depends(get_db)):
    return db.exec(select(Note).where(Note.date == date)).first()


@router.post("/api/notes")
def post_note(body: NoteRequest = Body(...), db: Session = Depends(get_db)):
    if body.rpe is not None and not (0 <= body.rpe <= 10):
        raise HTTPException(status_code=422, detail="rpe must be between 0 and 10")
    note = upsert_note(db, body.date, body.text, body.rpe)

    # RPE feeds session_strain's no-HR fallback (catch/analytics/strain.py), which load and
    # recovery both read — recompute so a saved RPE shows up without waiting for the next
    # sync. Non-blocking lock: a sync running at the same moment just skips this recompute,
    # and the next sync's own recompute will pick the new RPE up.
    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    return note
