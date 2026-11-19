"""Session 24 (docs/public-architecture.md §4): who am I, and delete my account.

Public deployment only — the personal install has no account to delete."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, SQLModel, delete

from catch.api import deps
from catch.api.deps import get_db, require_auth
from catch.coach import limits
from catch.core import tenant, tenant_hooks
from catch.core.config import settings
from catch.core.models import UserProfile
from catch.core.redact import redact
from catch.core.tenant import OwnedOrShared, OwnedStrict
from catch.sync import account_store, club_store, leaderboard_store

logger = logging.getLogger("catch.account")
router = APIRouter(dependencies=[Depends(require_auth)])
BUCKET = "piece-photos"
# Deleting an account is irreversible, so a long-lived (silently refreshed) token is not enough on its own: the person must
# have actually signed in recently. `amr[].timestamp` is that moment (it survives refresh; `iat` does not).
RECENT_SIGN_IN_SECONDS = 600


class DeleteAccount(BaseModel):
    confirm: str


@router.get("/api/me")
def me(request: Request, db: Session = Depends(get_db)):
    owner = tenant.current_owner()
    profile = db.get(UserProfile, owner)
    claims = getattr(request.state, "claims", None)
    return {
        "id": owner,
        "email": (profile.email if profile else None) or (claims.email if claims else None),
        "display_name": profile.display_name if profile else None,
        "deployment": settings.deployment,
    }


def purge_storage(access_token: str, owner: str) -> int:
    """Deletes the user's Storage objects with the user's own token (the bucket policies allow exactly that).
    Objects owned by a user block deletion of the auth user (Supabase docs), and database cascades never
    reach them, so this runs first."""
    base = f"{settings.supabase_url}/storage/v1"
    headers = {"apikey": settings.supabase_publishable_key, "authorization": f"Bearer {access_token}"}
    removed = 0
    with httpx.Client(timeout=15.0, headers=headers) as client:
        while True:
            listing = client.post(f"{base}/object/list/{BUCKET}", json={"prefix": owner, "limit": 100, "offset": 0})
            if listing.status_code == 404:
                return removed  # no such bucket on this project
            listing.raise_for_status()
            names = [f"{owner}/{o['name']}" for o in listing.json() if o.get("name")]
            if not names:
                return removed
            client.request("DELETE", f"{base}/object/{BUCKET}", json={"prefixes": names}).raise_for_status()
            removed += len(names)


def delete_global_rows(owner: str) -> None:
    """What the user left in tables no owner filter reaches: public leaderboard rows go, club ownership is handed on,
    reports/appeals/audit rows are detached from the person. Idempotent, and run BEFORE the auth user is deleted:
    once that succeeds the person can no longer sign in to retry, so nothing may be left that only a retry could clean."""
    leaderboard_store.delete_owner_data(owner)
    club_store.delete_owner_data(owner)  # ownership succession, then their own club rows; what they wrote stays, detached from them


def delete_user_rows(db: Session) -> None:
    """Service-layer deletion of everything the user owns. On Postgres deleting the profile is enough (every
    owned table cascades from it); on SQLite there is no cascade, so each table is cleared through the
    tenant-scoped ORM."""
    owner = tenant.current_owner()
    if tenant_hooks.uses_rls(db.get_bind()):
        db.exec(delete(UserProfile).where(UserProfile.id == owner))  # type: ignore[call-overload]
    else:
        for mapper in SQLModel._sa_registry.mappers:
            cls = mapper.class_
            if issubclass(cls, (OwnedStrict, OwnedOrShared)):
                db.exec(delete(cls))  # type: ignore[call-overload]
        db.exec(delete(UserProfile).where(UserProfile.id == owner))  # type: ignore[call-overload]
    db.commit()


def admin_delete_auth_user(owner: str) -> None:
    """The one place the secret key is used: GoTrue's admin delete. It removes auth.users, whose delete
    cascades to auth.sessions and refresh tokens, so the user's access tokens fail the next session check."""
    if not settings.supabase_secret_key:
        raise HTTPException(status_code=503, detail="Account deletion is not configured on this server")
    resp = httpx.request(
        "DELETE",
        f"{settings.supabase_url}/auth/v1/admin/users/{owner}",
        headers={"apikey": settings.supabase_secret_key},  # secret keys go in `apikey`, never `Authorization` (Supabase docs)
        json={"should_soft_delete": False},
        timeout=15.0,
    )
    if resp.status_code not in (200, 204, 404):
        logger.warning("auth admin delete failed: %s %s", resp.status_code, redact(resp.text[:200]))
        raise HTTPException(status_code=502, detail="Could not delete the sign-in account; your public posts and files were already removed — try again")


def _require_recent_sign_in(claims) -> None:
    from catch.core import supabase_auth  # public-only module: a personal install never imports it

    age = supabase_auth.seconds_since_sign_in(claims)
    if age is None or age > RECENT_SIGN_IN_SECONDS:
        raise HTTPException(status_code=403, detail="reauth_required")


@router.delete("/api/account")
def delete_account(body: DeleteAccount, request: Request, db: Session = Depends(get_db)):
    if not tenant.is_public():
        raise HTTPException(status_code=404, detail="Not available on a personal install")
    owner = tenant.current_owner()
    try:
        limits.check_rate(owner, "account")
    except limits.LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.message) from None
    if body.confirm != "DELETE":
        raise HTTPException(status_code=400, detail='Send {"confirm": "DELETE"} to delete this account')
    claims = request.state.claims
    _require_recent_sign_in(claims)
    token = request.headers["authorization"][len("bearer ") :].strip()
    try:
        removed = purge_storage(token, owner)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not remove stored files; nothing was deleted — try again") from None
    # End live provider grants (Whoop offers revocation) while the credentials still exist; best effort, never blocks deletion.
    from catch.sync import connections

    connections.revoke_all_for_account_deletion(db)
    delete_global_rows(owner)
    # The tombstone goes down before the auth user does: from the moment GoTrue deletes it, a token that is still
    # inside its signature lifetime must not be able to re-create the profile. If GoTrue refuses, the tombstone is lifted
    # so the person (still signed in, still existing) can simply try again — every step above is idempotent.
    account_store.mark_deleted(owner)
    try:
        admin_delete_auth_user(owner)
    except HTTPException:
        account_store.unmark_deleted(owner)
        raise
    from catch.core import supabase_auth

    supabase_auth.liveness.mark_dead(claims.session_id)
    delete_user_rows(db)  # a no-op on Postgres (the auth deletion already cascaded); the table-by-table clear on SQLite
    deps._profiles_known.discard(owner)
    return {"deleted": True, "files_removed": removed}
