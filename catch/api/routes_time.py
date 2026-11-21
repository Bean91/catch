"""Session 32 (docs/time.md): the athlete's time-zone preferences, and the app reporting the zone its device is in.

GET/PUT /api/time-zone — home zone (IANA) and the follow-my-device switch; changing either re-stamps records (their absolute times
never change) and recomputes the derived days in the background. PUT /api/time-zone/device — the app's report on open."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core import localtime, tenant

router = APIRouter(dependencies=[Depends(require_auth)])


class TimeZonePrefs(BaseModel):
    timezone: Optional[str] = Field(default=None, max_length=64)
    follow_device_zone: Optional[bool] = None


class DeviceZone(BaseModel):
    timezone: str = Field(max_length=64)


def _recompute_in_background(engine, owner: str, since) -> None:
    from catch.sync.scoring import recompute_scores

    with tenant.use_owner(owner), Session(engine) as session:
        recompute_scores(session, since=since)


@router.get("/api/time-zone")
def get_time_zone(db: Session = Depends(get_db)):
    return localtime.preferences(db)


@router.put("/api/time-zone")
def put_time_zone(body: TimeZonePrefs, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return localtime.preferences(db)
    try:
        out = localtime.set_preferences(db, home=fields.get("timezone", ...), follow=fields.get("follow_device_zone", ...))
    except ValueError:
        raise HTTPException(status_code=422, detail="Choose a time zone from the list.") from None
    since = localtime.pending_recompute_from(db)
    if since is not None:
        background_tasks.add_task(_recompute_in_background, db.get_bind(), tenant.current_owner(), since)
    return out


@router.put("/api/time-zone/device")
def report_device_zone(body: DeviceZone, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        out = localtime.report_device_zone(db, body.timezone)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unknown time zone.") from None
    since = localtime.pending_recompute_from(db)
    if out["changed"]:
        # A new zone from now on moves "today": refresh today's (and any re-stamped) rows.
        background_tasks.add_task(_recompute_in_background, db.get_bind(), tenant.current_owner(), since or localtime.today(db))
    return out
