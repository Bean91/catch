from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterator

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, select

from catch.core.db import engine
from catch.core.models import ApiToken
from catch.core.principal import ATHLETE, Principal, principal_from_token
from catch.core.security import SESSION_COOKIE_NAME, verify_session_cookie


def get_db() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def as_utc(value: datetime | None) -> datetime | None:
    # Query params like ?from=2026-10-01 parse to a naive datetime; our DateTime columns
    # require tz-aware values, so assume UTC rather than 500ing on every date-range filter.
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def require_auth(request: Request) -> None:
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not verify_session_cookie(cookie):
        raise HTTPException(status_code=401, detail="Not authenticated")


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _tool_principal(request: Request, db: Session) -> Principal:
    """Cookie OR a per-device bearer token — scoped to the tool-call endpoints only (the MCP
    server authenticates this way so it can run on a laptop while Catch runs on the Pi). Key
    management, coach settings, and conversation history stay cookie-only via require_auth:
    a stolen device token must not be able to read the Anthropic key or mint more tokens.

    Returns the caller's Principal (session 22): the cookie and role-less tokens are the athlete;
    a `role="coach"` token is a coach, which `call_tool` restricts to the coaching tools."""
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if verify_session_cookie(cookie):
        return ATHLETE
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header[len("bearer ") :].strip()
        if raw_token:
            row = db.exec(select(ApiToken).where(ApiToken.token_hash == hash_token(raw_token))).first()
            if row is not None:
                row.last_used_at = datetime.now(timezone.utc)
                db.commit()
                return principal_from_token(row.id, row.role, row.display_name)
    raise HTTPException(status_code=401, detail="Not authenticated")


def require_tool_auth(request: Request, db: Session = Depends(get_db)) -> Principal:
    """Athlete-only bearer access: a coach-role token is refused (403), so a route that adopts
    this dependency can never hand a coach's token the athlete's data by accident."""
    principal = _tool_principal(request, db)
    if not principal.is_athlete:
        raise HTTPException(status_code=403, detail="This token's role can't use this endpoint")
    return principal


def require_tool_auth_allow_coach(request: Request, db: Session = Depends(get_db)) -> Principal:
    """The explicit opt-in: only the shared tool endpoints use it, and `call_tool` then restricts a
    coach principal to the coaching tools."""
    return _tool_principal(request, db)
