from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core import tenant
from catch.core.security import SESSION_COOKIE_NAME, make_session_cookie, verify_password

def personal_only() -> None:
    """Cookie login is the personal install's. In the public deployment identity is Supabase Auth, and the source
    OAuth round-trips (a browser redirect, so no Authorization header) need a signed-state callback that isn't
    built yet — so they say so instead of silently attaching a token to the wrong user."""
    if tenant.is_public():
        raise HTTPException(status_code=404, detail="Not available in the public deployment")


router = APIRouter(dependencies=[Depends(personal_only)])

class LoginRequest(BaseModel):
    password: str


@router.post("/api/login")
def login(body: LoginRequest, response: Response):
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    response.set_cookie(
        SESSION_COOKIE_NAME,
        make_session_cookie(),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return {"ok": True}


@router.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


def _legacy_start(provider: str):
    """The personal install's original links (`/auth/<provider>/start`): same signed-state flow, delivered as a redirect."""
    from catch.api.routes_connections import authorize_url_for

    redirect = RedirectResponse("/")
    redirect.headers["location"] = authorize_url_for(provider, redirect, tenant.current_owner())
    return redirect


@router.get("/auth/withings/start", dependencies=[Depends(require_auth)])
def withings_start():
    return _legacy_start("withings")


@router.get("/auth/whoop/start", dependencies=[Depends(require_auth)])
def whoop_start():
    return _legacy_start("whoop")


@router.post("/auth/whoop/disconnect", dependencies=[Depends(require_auth)])
def whoop_disconnect(db: Session = Depends(get_db)):
    from catch.sync import whoop_client

    return whoop_client.disconnect(db)


@router.get("/api/whoop/test", dependencies=[Depends(require_auth)])
def whoop_test(db: Session = Depends(get_db)):
    """The in-app manual connection test: counts only, never tokens or personal details."""
    from catch.sync import whoop_client

    if not whoop_client.configured():
        return {"connected": False, "error": "Whoop isn't configured on this server."}
    try:
        return whoop_client.check(db)
    except whoop_client.WhoopReconnectNeeded as exc:
        return {"connected": False, "reconnect": True, "error": str(exc)}
    except whoop_client.WhoopError as exc:
        return {"connected": False, "error": str(exc)}
