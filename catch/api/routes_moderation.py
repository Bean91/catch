"""Session 26 (docs/leaderboards.md §Moderation): the moderator queue. A moderator is a Supabase user id listed in the
CATCH_MODERATOR_IDS server secret; everyone else gets 404, so the endpoints don't advertise themselves. Every action needs
a written reason and is recorded in the append-only moderation log by leaderboard_store.set_entry_status."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from catch.api.deps import require_auth
from catch.api.routes_leaderboards import public_only
from catch.core import config, tenant
from catch.sync import account_store, club_store, restrictions
from catch.sync import leaderboard_store as store


def require_moderator(request: Request) -> None:
    if tenant.current_owner() not in config.settings.moderators:
        raise HTTPException(status_code=404, detail="Not found")
    # Moderators can see reports and reasons for other people's content, so their session needs a second factor: a token that
    # carries `aal2` (Supabase MFA completed on this session), not just a password.
    claims = getattr(request.state, "claims", None)
    if config.settings.moderator_require_aal2 and getattr(claims, "aal", None) != "aal2":
        raise HTTPException(status_code=403, detail="mfa_required")


def _seen(kind: str, target: Optional[str] = None) -> None:
    """Moderator reads are accountable: every detail view lands in an append-only log."""
    account_store.log_moderator_access(tenant.current_owner(), kind, target)


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
    _seen("queue")
    return store.queue()


@router.get("/api/moderation/entries/{entry_id}")
def entry(entry_id: str):
    _seen("entry", entry_id)
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


# ---------------------------------------------------------------- clubs (session 27)

class ClubActionBody(BaseModel):
    action: str
    reason: str
    target_id: Optional[str] = None
    target_type: Optional[str] = None


@router.get("/api/moderation/clubs/queue")
def club_queue():
    _seen("queue")
    return {"reports": club_store.queue()}


@router.get("/api/moderation/clubs/{club_id}")
def club_detail(club_id: str):
    _seen("club", club_id)
    found = club_store.club_for_moderator(club_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Not found")
    return found


@router.post("/api/moderation/clubs/{club_id}/action")
def club_action(club_id: str, body: ClubActionBody):
    return _call(club_store.moderate, tenant.current_owner(), club_id, body.action, body.reason, body.target_id, body.target_type)


# ---------------------------------------------------------------- account restrictions (session 28)

class RestrictBody(BaseModel):
    user_id: str
    scope: str
    reason: str
    reason_code: str = "other"
    days: Optional[int] = None


def _restr(fn, *args):
    try:
        return fn(*args)
    except restrictions.RestrictionError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@router.get("/api/moderation/restrictions")
def restriction_queue():
    _seen("restrictions")
    return {"restrictions": restrictions.queue()}


@router.post("/api/moderation/restrictions")
def restrict(body: RestrictBody):
    return _restr(restrictions.restrict, tenant.current_owner(), body.user_id, body.scope, body.reason_code, body.reason, body.days)


@router.post("/api/moderation/restrictions/{restriction_id}/lift")
def lift(restriction_id: int, body: ClubActionBody):
    return _restr(restrictions.lift, tenant.current_owner(), restriction_id, body.reason)


@router.post("/api/moderation/restrictions/{restriction_id}/resolve")
def resolve_restriction_appeal(restriction_id: int, body: ResolveBody):
    return _restr(restrictions.resolve_appeal, tenant.current_owner(), restriction_id, body.outcome, body.reason)


@router.get("/api/moderation/actions")
def action_log():
    _seen("actions")
    return {"actions": restrictions.actions()}
