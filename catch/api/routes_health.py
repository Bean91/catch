"""Session 30 (docs/mobile/health-data.md): consent and import endpoints for Apple Health / Health Connect.

Public deployment only (the store apps exist for it). Every route needs the athlete's own bearer token; an MCP/coach device token
reaches none of these. Nothing is accepted without a recorded in-app consent, and what is accepted is limited to the categories
the person ticked."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.coach import limits
from catch.core import tenant
from catch.core.owner import current_owner_id
from catch.sync import health_import as svc

router = APIRouter(dependencies=[Depends(require_auth)])


def _public_only() -> None:
    if not tenant.is_public():
        raise HTTPException(status_code=404, detail="Not found")


def _throttle(owner_id: str) -> None:
    try:
        limits.check_rate(owner_id, "health")
    except limits.LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.message) from None


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.HealthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


class ConsentBody(BaseModel):
    platform: str
    categories: list[str] = Field(max_length=8)


class RevokeBody(BaseModel):
    platform: str
    delete_data: bool = False


class ImportBody(BaseModel):
    platform: str
    workouts: list[dict] = Field(default_factory=list)
    readings: list[dict] = Field(default_factory=list)


@router.get("/api/health/status")
def health_status(db: Session = Depends(get_db)):
    _public_only()
    return svc.status(db)


@router.put("/api/health/consent")
def put_consent(body: ConsentBody, db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    _public_only()
    _throttle(owner_id)
    return _call(svc.grant_consent, db, body.platform, body.categories)


@router.post("/api/health/consent/revoke")
def revoke(body: RevokeBody, db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    _public_only()
    _throttle(owner_id)
    return _call(svc.revoke_consent, db, body.platform, delete_data=body.delete_data)


@router.post("/api/health/import")
def import_health(body: ImportBody = Body(...), db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    _public_only()
    _throttle(owner_id)
    return _call(svc.import_batch, db, body.platform, body.workouts, body.readings)


@router.delete("/api/health/data")
def delete_data(db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    _public_only()
    _throttle(owner_id)
    return svc.delete_imported(db)
