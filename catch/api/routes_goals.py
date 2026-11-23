"""Session 36: goals (catch/sync/goals.py). Plain `def` routes; the tenant hooks scope every read and write to the signed-in owner."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core import localtime
from catch.sync import goals

router = APIRouter(dependencies=[Depends(require_auth)])


def _guard(fn):
    try:
        return fn()
    except goals.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except goals.GoalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/api/goals")
def list_goals(view: str = Query("all", pattern="^(active|history|all)$"), db: Session = Depends(get_db)):
    return {"goals": goals.list_goals(db, None if view == "all" else view)}


@router.post("/api/goals")
def create_goal(body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    row = _guard(lambda: goals.create(db, body))
    return goals.goal_dict(db, row, localtime.today(db))


@router.patch("/api/goals/{goal_id}")
def update_goal(goal_id: int, body: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    row = _guard(lambda: goals.update(db, goal_id, body))
    return goals.goal_dict(db, row, localtime.today(db))


@router.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    _guard(lambda: goals.delete(db, goal_id))
    return {"deleted": goal_id}
