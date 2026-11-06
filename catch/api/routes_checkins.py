from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from datetime import date as date_

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from catch.api.deps import get_db, require_auth
from catch.core.models import CheckIn

router = APIRouter(dependencies=[Depends(require_auth)])

_SLIDER_FIELDS = ("soreness", "stress", "mood", "sleep_quality")


class CheckInRequest(BaseModel):
    # Typed as `date_` (the datetime.date alias), not `date` — a field literally named
    # `date` whose own type is also `date` self-shadows once pydantic resolves this class's
    # deferred (PEP 563) string annotations against its own namespace, where `date` the
    # class attribute (this field's default, None) has already replaced `date` the type by
    # the time that happens. Same reason catch/core/models.py imports this alias.
    date: date_ | None = None  # defaults to today — "editable later that day" needs no date arg from the sheet
    soreness: int | None = None
    stress: int | None = None
    mood: int | None = None
    sleep_quality: int | None = None
    niggle_area: str | None = None
    niggle_severity: int | None = None  # 1-3
    note: str | None = None


def _validate(body: CheckInRequest) -> None:
    for field in _SLIDER_FIELDS:
        value = getattr(body, field)
        if value is not None and not (1 <= value <= 5):
            raise HTTPException(status_code=422, detail=f"{field} must be between 1 and 5")
    if body.niggle_severity is not None and not (1 <= body.niggle_severity <= 3):
        raise HTTPException(status_code=422, detail="niggle_severity must be between 1 and 3")
    if body.niggle_severity is not None and not body.niggle_area:
        raise HTTPException(status_code=422, detail="niggle_severity requires niggle_area")


@router.get("/api/checkins/today")
def get_today_checkin(db: Session = Depends(get_db)):
    row = db.get(CheckIn, date.today())
    return {"date": date.today(), "completed": row is not None, "checkin": row}


@router.get("/api/checkins")
def list_checkins(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(CheckIn)
    if from_:
        stmt = stmt.where(CheckIn.date >= from_)
    if to:
        stmt = stmt.where(CheckIn.date <= to)
    return db.exec(stmt.order_by(CheckIn.date)).all()


@router.post("/api/checkins")
def post_checkin(body: CheckInRequest = Body(...), db: Session = Depends(get_db)):
    _validate(body)
    day = body.date or date.today()
    row = db.get(CheckIn, day)
    if row is None:
        row = CheckIn(date=day)
        db.add(row)
    for field in (*_SLIDER_FIELDS, "niggle_area", "niggle_severity", "note"):
        setattr(row, field, getattr(body, field))
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    # The subjective check-in feeds recovery_score directly (catch/sync/scoring.py's
    # day_recovery) — recompute so Today reflects it immediately. Same non-blocking-lock
    # caveat as every other write-triggered recompute in this app (routes_notes.py,
    # routes_analytics.put_settings): a sync running at this exact moment just skips this
    # one, and picks the new check-in up on its own next recompute.
    from catch.sync.scoring import recompute_scores

    recompute_scores(db)
    # recompute_scores commits internally, which (SQLAlchemy's expire_on_commit default)
    # expires every attribute on `row` — returning it unrefreshed can serialize as `{}` (see
    # the identical bug/fix in routes_illness.py's dismiss_illness_flag). db.get() forces a
    # fresh read instead of trusting whatever's still cached in-memory.
    return db.get(CheckIn, day)


def niggle_streak_days(db: Session, through: date) -> int:
    """How many consecutive days up to and including `through` have a niggle recorded —
    task Part A.3's "a niggle that lasts 3+ days" flag, shared by GET /api/today and the
    coach's memory block (catch/coach/memory.py) so both agree on one number."""
    streak = 0
    day = through
    while True:
        row = db.get(CheckIn, day)
        if row is None or not row.niggle_area:
            break
        streak += 1
        day -= timedelta(days=1)
    return streak
