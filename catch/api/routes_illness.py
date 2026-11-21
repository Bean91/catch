from __future__ import annotations

from catch.core import tenant
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from catch.api.deps import get_db, require_auth
from catch.core.models import DailyScore, IllnessAck

router = APIRouter(dependencies=[Depends(require_auth)])

_DISMISS_REASONS = {"alcohol", "travel", "late_night", "vaccine", "other"}


class DismissRequest(BaseModel):
    reason: str


class MarkRequest(BaseModel):
    correct: bool


def _get_or_create_ack(db: Session, day: date) -> IllnessAck:
    ack = db.get(IllnessAck, tenant.pk(day))
    if ack is None:
        ack = IllnessAck(date=day)
        db.add(ack)
    return ack


@router.post("/api/illness/{day}/dismiss")
def dismiss_illness_flag(day: date, body: DismissRequest = Body(...), db: Session = Depends(get_db)):
    if body.reason not in _DISMISS_REASONS:
        raise HTTPException(status_code=422, detail=f"reason must be one of {sorted(_DISMISS_REASONS)}")
    # A dismissal is a direct, explicit user action — unlike recompute_scores' insert-only
    # writes to this table, it's fine (and the point) to overwrite these two fields here.
    ack = _get_or_create_ack(db, day)
    ack.dismissed = True
    ack.dismiss_reason = body.reason
    ack.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ack)

    # A confound reason excludes this day from future illness baselines (catch/sync/
    # scoring.py's day_illness) — recompute now so that takes effect immediately, same
    # pattern as every other write-triggered recompute in this app.
    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    # recompute_scores commits internally, which (SQLAlchemy's expire_on_commit default)
    # expires every attribute on `ack` — returning it unrefreshed serializes as `{}`, a real
    # bug this test suite caught. db.get() forces a fresh read rather than trusting stale
    # in-memory state.
    return db.get(IllnessAck, tenant.pk(day))


@router.post("/api/illness/{day}/mark")
def mark_backtest(day: date, body: MarkRequest = Body(...), db: Session = Depends(get_db)):
    ack = _get_or_create_ack(db, day)
    ack.backtest_mark = "correct" if body.correct else "incorrect"
    ack.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ack)
    return ack


@router.get("/api/illness/backtest")
def illness_backtest(days: int = Query(365, ge=1, le=3660), db: Session = Depends(get_db)):
    """Task Part B.4: every night history would have flagged (watch or likely), with
    whatever the athlete has marked right/wrong so far, plus precision over what's actually
    been marked (never over everything — most nights will simply be unmarked).

    Session 33: reads only the date and the stored illness result (no recomputation, and not the recovery/strain/load JSON of
    every day), the last `days` days (default a year), and skips the "none" nights in SQL — this card used to load every
    daily_scores row ever, all columns, to show a handful of nights."""
    from catch.core import localtime

    since = localtime.today(db) - timedelta(days=days)
    rows = db.exec(
        select(DailyScore.date, DailyScore.illness_json)
        .where(DailyScore.date >= since, DailyScore.illness_json.is_not(None), DailyScore.illness_json.not_like('%"level": "none"%'))
        .order_by(DailyScore.date)
    ).all()
    acks = {a.date: a for a in db.exec(select(IllnessAck).where(IllnessAck.date >= since)).all()}

    flagged = []
    for day, illness_json in rows:
        illness = json.loads(illness_json)
        if illness["level"] == "none":
            continue
        ack = acks.get(day)
        flagged.append(
            {
                "date": day,
                "level": illness["level"],
                "deviated_count": illness["deviated_count"],
                "explanation": illness["explanation"],
                "dismissed": ack.dismissed if ack else False,
                "dismiss_reason": ack.dismiss_reason if ack else None,
                "backtest_mark": ack.backtest_mark if ack else None,
            }
        )

    marked = [f for f in flagged if f["backtest_mark"] is not None]
    correct = [f for f in marked if f["backtest_mark"] == "correct"]
    precision = (len(correct) / len(marked)) if marked else None
    return {"flagged": flagged, "marked_count": len(marked), "precision": precision}
