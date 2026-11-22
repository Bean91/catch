"""Session 32: first-run setup progress (docs/onboarding.md).

Progress lives on the person's own profile row (user_profiles.onboarding_*), so it resumes on any device. On the public build a
signed-in account whose setup isn't completed is shown /welcome; accounts that existed before this session were marked completed
by migration 0011. The personal (Pi) install never shows it unprompted — Settings can still open it. Nothing here touches a
provider credential: connecting goes through the existing connection routes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core import tenant
from catch.core.models import UserProfile

router = APIRouter(dependencies=[Depends(require_auth)])

# Session 34 added "privacy". Progress is stored as an index, so someone saved mid-setup at the old "sync" (3) resumes on "privacy",
# which they haven't seen — intended. The privacy step stores nothing here: each choice is saved at once through the same endpoints as
# Settings → Privacy (AI sharing, leaderboards), so resuming re-reads those rows, and completing or skipping setup changes none of them.
STEPS = ("welcome", "connections", "preferences", "privacy", "sync", "done")
COMPLETED = "completed"


class OnboardingUpdate(BaseModel):
    step: Optional[int] = Field(default=None, ge=0, le=len(STEPS) - 1)
    skipped: Optional[list[str]] = Field(default=None, max_length=10)
    complete: bool = False
    restart: bool = False


def _profile(db: Session) -> UserProfile:
    owner = tenant.current_owner()
    profile = db.get(UserProfile, owner)
    if profile is None:
        profile = UserProfile(id=owner)
        db.add(profile)
        db.flush()
    return profile


def _state(profile: UserProfile) -> dict:
    data = json.loads(profile.onboarding_json) if profile.onboarding_json else {}
    completed = profile.onboarding_state == COMPLETED
    return {
        "state": COMPLETED if completed else "pending",
        "step": profile.onboarding_step or 0,
        "steps": list(STEPS),
        "skipped": data.get("skipped", []),
        "completed_at": profile.onboarding_completed_at,
        # Only a public account is sent to setup automatically; the Pi's single owner opens it from Settings if they want it.
        "show": tenant.is_public() and not completed,
    }


@router.get("/api/onboarding")
def get_onboarding(db: Session = Depends(get_db)):
    return _state(_profile(db))


@router.put("/api/onboarding")
def put_onboarding(body: OnboardingUpdate, db: Session = Depends(get_db)):
    profile = _profile(db)
    data = json.loads(profile.onboarding_json) if profile.onboarding_json else {}
    if body.restart:
        profile.onboarding_state, profile.onboarding_step, profile.onboarding_completed_at = None, 0, None
    if body.step is not None:
        profile.onboarding_step = body.step
    if body.skipped is not None:
        from catch.sync.connections import PROVIDERS

        data["skipped"] = sorted({p for p in body.skipped if p in PROVIDERS})
    if body.complete:
        profile.onboarding_state = COMPLETED
        profile.onboarding_step = len(STEPS) - 1
        profile.onboarding_completed_at = datetime.now(timezone.utc)
    profile.onboarding_json = json.dumps(data) if data else None
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _state(profile)


def _first_window(owner: str, sources: list[str]) -> None:
    """The first history window for each newly connected source, after the response has gone: the person is never kept waiting
    for an import. If the process stops first (a scaled-to-zero replica), the scheduled sync tick carries on from the same cursor."""
    from catch.sync.scheduler import run_sync

    with tenant.use_owner(owner):
        for source in sources:
            try:
                run_sync(source, manual=True)
            except Exception:  # noqa: BLE001 — one provider never stops the others; the card shows its state
                pass


@router.post("/api/onboarding/start-sync")
def start_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Start importing for every source this person connected. Returns at once with which ones were started; progress is read from
    GET /api/connections like anywhere else."""
    from catch.sync import connections
    from catch.sync.scheduler import SOURCES

    started = []
    for source in SOURCES:
        conn = connections.get(db, source)
        if conn is None or conn.status == connections.NEEDS_RECONNECT:
            continue
        started.append(source)
    if started:
        background_tasks.add_task(_first_window, tenant.current_owner(), started)
    return {"started": started}
