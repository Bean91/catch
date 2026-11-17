"""Session 26 (docs/leaderboards.md §Moderation): the moderator queue. A moderator is a Supabase user id listed in the
CATCH_MODERATOR_IDS server secret; everyone else gets 404, so the endpoints don't advertise themselves. Every action needs
a written reason and is recorded in the append-only moderation log by leaderboard_store.set_entry_status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from catch.api.deps import require_auth
from catch.api.routes_leaderboards import public_only
from catch.core import config, tenant
from catch.sync import leaderboard_store as store


def require_moderator() -> None:
    if tenant.current_owner() not in config.settings.moderators:
        raise HTTPException(status_code=404, detail="Not found")


router = APIRouter(dependencies=[Depends(public_only), Depends(require_auth), Depends(require_moderator)])


class ActionBody(BaseModel):
    action: str
    reason: str


class ResolveBody(BaseModel):
    outcome: str
    reason: str


def _call(fn, *args):
    try:
        return fn(*args)
    except store.StoreError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@router.get("/api/moderation/queue")
def queue():
    return store.queue()


@router.get("/api/moderation/entries/{entry_id}")
def entry(entry_id: str):
    found = store.entry_for_moderator(entry_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Not found")
    return found


@router.post("/api/moderation/entries/{entry_id}/action")
def action(entry_id: str, body: ActionBody):
    return _call(store.moderate, tenant.current_owner(), entry_id, body.action, body.reason)


@router.post("/api/moderation/appeals/{appeal_id}/resolve")
def resolve(appeal_id: int, body: ResolveBody):
    return _call(store.resolve_appeal, tenant.current_owner(), appeal_id, body.outcome, body.reason)
