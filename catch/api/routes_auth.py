from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core.security import SESSION_COOKIE_NAME, make_session_cookie, verify_password
from catch.sync import withings_client

router = APIRouter()

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
