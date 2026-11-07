from __future__ import annotations

"""Session 18 (see PLAN.md): training intelligence & recommendations — profile/trends/
distribution/consistency/insights are plain reads over catch.sync.training_intelligence's
gather_* functions; dismiss/save/rate are direct mutations on an existing Recommendation row,
same `db.commit(); db.refresh(row)` + re-`db.get(...)` precaution as routes_illness.py (an
in-memory object's attributes are expired by SQLAlchemy's default on commit)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core.models import Recommendation
from catch.core.settings_store import get_settings
from catch.sync import training_intelligence

router = APIRouter(dependencies=[Depends(require_auth)])

_RATINGS = {"useful", "not_useful"}


@router.get("/api/training-intelligence/profile")
def get_training_profile(db: Session = Depends(get_db)):
    return training_intelligence.gather_training_profile(db, get_settings(db))


@router.get("/api/training-intelligence/trends")
def get_performance_trends(piece_type: str | None = Query(None, alias="piece_type"), db: Session = Depends(get_db)):
    return training_intelligence.gather_performance_trends(db, get_settings(db), piece_type)


@router.get("/api/training-intelligence/distribution")
def get_training_distribution(weeks: int = Query(12, ge=1, le=52), db: Session = Depends(get_db)):
    return training_intelligence.gather_training_distribution(db, get_settings(db), weeks)


@router.get("/api/training-intelligence/consistency")
def get_training_consistency(weeks: int | None = Query(None, ge=1, le=52), db: Session = Depends(get_db)):
    return training_intelligence.gather_training_consistency(db, get_settings(db), weeks)


@router.get("/api/training-intelligence/insights")
def get_training_insights(db: Session = Depends(get_db)):
    return {"insights": training_intelligence.gather_training_insights(db, get_settings(db))}


@router.get("/api/training-intelligence/recommendations")
def get_recommendations(
    status: str = Query("active", pattern="^(active|dismissed|all)$"),
    rec_type: str | None = Query(None, alias="type"),
    db: Session = Depends(get_db),
):
    return {"recommendations": training_intelligence.list_recommendations(db, status, rec_type)}


class SaveRequest(BaseModel):
    saved: bool


class RateRequest(BaseModel):
    rating: str


def _get_or_404(db: Session, id: int) -> Recommendation:
    row = db.get(Recommendation, id)
    if row is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return row


@router.post("/api/training-intelligence/recommendations/{id}/dismiss")
def dismiss_recommendation(id: int, db: Session = Depends(get_db)):
    row = _get_or_404(db, id)
    row.dismissed = True
    row.dismissed_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    # recommendation_dict (not the bare ORM row) — every other endpoint here returns the same
    # parsed-evidence/`active`-flag shape (routes_tests.py-style consistency: a mutation
    # response should match its sibling GET's row shape, not a different one the caller then
    # has to reconcile).
    return training_intelligence.recommendation_dict(db.get(Recommendation, id))


@router.post("/api/training-intelligence/recommendations/{id}/save")
def save_recommendation(id: int, body: SaveRequest = Body(...), db: Session = Depends(get_db)):
    row = _get_or_404(db, id)
    row.saved = body.saved
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return training_intelligence.recommendation_dict(db.get(Recommendation, id))


@router.post("/api/training-intelligence/recommendations/{id}/rate")
def rate_recommendation(id: int, body: RateRequest = Body(...), db: Session = Depends(get_db)):
    if body.rating not in _RATINGS:
        raise HTTPException(status_code=422, detail=f"rating must be one of {sorted(_RATINGS)}")
    row = _get_or_404(db, id)
    row.rating = body.rating
    row.rated_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return training_intelligence.recommendation_dict(db.get(Recommendation, id))
