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
from catch.core import tenant, tenant_hooks
from catch.core.config import settings
from catch.core.models import UserProfile
from catch.core.redact import redact
from catch.core.tenant import OwnedOrShared, OwnedStrict

logger = logging.getLogger("catch.account")
router = APIRouter(dependencies=[Depends(require_auth)])
BUCKET = "piece-photos"


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
        raise HTTPException(status_code=502, detail="Could not delete the sign-in account; nothing else was changed — try again")


@router.delete("/api/account")
def delete_account(body: DeleteAccount, request: Request, db: Session = Depends(get_db)):
    if not tenant.is_public():
        raise HTTPException(status_code=404, detail="Not available on a personal install")
    if body.confirm != "DELETE":
        raise HTTPException(status_code=400, detail='Send {"confirm": "DELETE"} to delete this account')
    owner = tenant.current_owner()
    token = request.headers["authorization"][len("bearer ") :].strip()
    try:
        removed = purge_storage(token, owner)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not remove stored files; nothing was deleted — try again") from None
    # The auth user goes first: it is the step that can fail for a reason outside our database, and once it is
    # gone the cascade removes the profile and every owned row (and the user's sessions stop validating).
    admin_delete_auth_user(owner)
    delete_user_rows(db)
    deps._profiles_known.discard(owner)
    return {"deleted": True, "files_removed": removed}
