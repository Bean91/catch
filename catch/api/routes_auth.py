from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core import tenant
from catch.core.security import SESSION_COOKIE_NAME, make_session_cookie, verify_password
from catch.sync import withings_client

def personal_only() -> None:
    """Cookie login is the personal install's. In the public deployment identity is Supabase Auth, and the source
    OAuth round-trips (a browser redirect, so no Authorization header) need a signed-state callback that isn't
    built yet — so they say so instead of silently attaching a token to the wrong user."""
    if tenant.is_public():
        raise HTTPException(status_code=404, detail="Not available in the public deployment")


router = APIRouter(dependencies=[Depends(personal_only)])

WITHINGS_STATE_COOKIE = "withings_oauth_state"


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


@router.get("/auth/withings/start", dependencies=[Depends(require_auth)])
def withings_start():
    state = secrets.token_urlsafe(24)
    url = withings_client.authorize_url(state)
    redirect = RedirectResponse(url)
    redirect.set_cookie(WITHINGS_STATE_COOKIE, state, httponly=True, samesite="lax", max_age=600)
    return redirect


@router.get("/auth/withings/callback", dependencies=[Depends(require_auth)])
def withings_callback(code: str, state: str, request: Request, response: Response, db: Session = Depends(get_db)):
    expected_state = request.cookies.get(WITHINGS_STATE_COOKIE)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(status_code=400, detail="Invalid or missing OAuth state")
    withings_client.exchange_code(db, code)
    response.delete_cookie(WITHINGS_STATE_COOKIE)
    return {"ok": True, "message": "Withings connected"}


WHOOP_STATE_COOKIE = "whoop_oauth_state"


@router.get("/auth/whoop/start", dependencies=[Depends(require_auth)])
def whoop_start():
    from catch.sync import whoop_client

    if not whoop_client.configured():
        raise HTTPException(status_code=409, detail="Whoop isn't configured on this server (see .env.example).")
    state = whoop_client.new_state()
    redirect = RedirectResponse(whoop_client.authorize_url(state))
    redirect.set_cookie(WHOOP_STATE_COOKIE, state, httponly=True, samesite="lax", max_age=600)
    return redirect


@router.get("/auth/whoop/callback", dependencies=[Depends(require_auth)])
def whoop_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    """Unlike Withings' JSON reply, this lands the browser back on Settings."""
    from catch.sync import whoop_client

    expected = request.cookies.get(WHOOP_STATE_COOKIE)
    if not expected or not state or not secrets.compare_digest(expected, state):
        raise HTTPException(status_code=400, detail="Invalid or missing OAuth state")
    if error or not code:
        redirect = RedirectResponse("/settings?whoop=denied", status_code=303)
    else:
        try:
            whoop_client.exchange_code(db, code)
            redirect = RedirectResponse("/settings?whoop=connected", status_code=303)
        except whoop_client.WhoopError:
            redirect = RedirectResponse("/settings?whoop=failed", status_code=303)
    redirect.delete_cookie(WHOOP_STATE_COOKIE)
    return redirect


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
