"""The consent half of MCP OAuth (session 28): the signed-in person approves or refuses an app, and manages the apps they approved.

The SDK's /authorize endpoint only redirects here (catch/mcp_server/oauth.py); nothing is granted until the person says so on this
page, authenticated like every other API call. Public deployment only."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.api.ratelimit import throttle
from catch.api.routes_leaderboards import public_only
from catch.mcp_server import oauth

router = APIRouter(prefix="/api/oauth", dependencies=[Depends(public_only), Depends(require_auth)])


def _enabled() -> None:
    from catch.core.config import settings

    if not settings.mcp_oauth_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def _request(req: str) -> dict:
    try:
        return oauth.verify_request(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/authorization-request", dependencies=[Depends(_enabled)])
def authorization_request(req: str):
    throttle("admin")
    data = _request(req)
    info = oauth._client_info(None, data["c"])  # type: ignore[arg-type]
    if info is None or data["r"] not in [str(u) for u in (info.redirect_uris or [])]:
        raise HTTPException(status_code=400, detail="This app is not registered.")
    return {
        "client_name": (info.client_name or "An app").strip(),
        "redirect_host": urlsplit(data["r"]).hostname,
        "scopes": [{"scope": s, "text": oauth.SCOPE_TEXT[s]} for s in data["s"]],
    }


class AuthorizeBody(BaseModel):
    req: str
    approve: bool = False
    scopes: Optional[list[str]] = Field(default=None, max_length=4)


@router.post("/authorize", dependencies=[Depends(_enabled)])
def authorize(body: AuthorizeBody, db: Session = Depends(get_db)):
    throttle("admin")
    data = _request(body.req)
    info = oauth._client_info(None, data["c"])  # type: ignore[arg-type]
    if info is None or data["r"] not in [str(u) for u in (info.redirect_uris or [])]:
        raise HTTPException(status_code=400, detail="This app is not registered.")
    chosen = [s for s in (body.scopes if body.scopes is not None else data["s"]) if s in data["s"]]
    if "catch:write" in chosen and "catch:read" not in chosen:
        chosen.append("catch:read")  # write implies read
    if not body.approve or not chosen:
        return {"redirect_url": oauth.redirect_after_decision(data, code=None, error="access_denied")}
    try:
        code = oauth.create_code(db, client_id=data["c"], redirect_uri=data["r"], explicit=data["x"], challenge=data["ch"], scopes=chosen, resource=data["res"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"redirect_url": oauth.redirect_after_decision(data, code=code)}


@router.get("/grants")
def grants(db: Session = Depends(get_db)):
    return {"grants": oauth.list_grants(db)}


@router.delete("/grants/{grant_id}")
def end_grant(grant_id: str, db: Session = Depends(get_db)):
    throttle("token")
    if not oauth.revoke_grant(db, grant_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@router.delete("/grants")
def end_all(db: Session = Depends(get_db)):
    throttle("token")
    return {"revoked": oauth.revoke_all(db)}
