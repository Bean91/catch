from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterator

from fastapi import Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session, select

from catch.core import device_tokens, tenant
from catch.core.db import engine
from catch.core.models import ApiToken
from catch.core.principal import ATHLETE, Principal, athlete_for, principal_from_token
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


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[len("bearer ") :].strip() if header.lower().startswith("bearer ") else ""


def _looks_like_jwt(raw: str) -> bool:
    return raw.count(".") == 2


_profiles_known: set[str] = set()


def ensure_profile(claims) -> None:
    """Second half of the auth.users -> user_profiles sync (the first is a database trigger): the first
    request of a user the trigger somehow missed creates the profile under that user's own RLS context."""
    if claims.sub in _profiles_known:
        return
    from catch.core.models import UserProfile

    with tenant.use_owner(claims.sub), Session(engine) as session:
        if session.get(UserProfile, claims.sub) is None:
            session.add(UserProfile(id=claims.sub, email=claims.email))
            session.commit()
    if len(_profiles_known) > 10000:
        _profiles_known.clear()
    _profiles_known.add(claims.sub)


async def _authenticate_jwt(raw: str):
    from catch.core import supabase_auth

    try:
        claims = await run_in_threadpool(supabase_auth.authenticate_bearer, raw)
        await run_in_threadpool(ensure_profile, claims)
    except supabase_auth.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers={"WWW-Authenticate": "Bearer"}) from None
    # Set here, in the request's own task: a sync dependency runs in a thread copy of the context, so
    # anything it set would never reach the endpoint.
    tenant.set_owner(claims.sub)
    return claims


async def require_auth(request: Request) -> None:
    if tenant.is_public():
        raw = _bearer(request)
        if not raw or not _looks_like_jwt(raw):
            raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
        request.state.claims = await _authenticate_jwt(raw)
        return
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not verify_session_cookie(cookie):
        raise HTTPException(status_code=401, detail="Not authenticated")


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _tool_principal(request: Request, db: Session) -> Principal:
    """Cookie OR a per-device bearer token — scoped to the tool-call endpoints only (the MCP
    server authenticates this way so it can run on a laptop while Catch runs on the Pi). Key
    management, coach settings, and conversation history stay cookie-only via require_auth:
    a stolen device token must not be able to read the Anthropic key or mint more tokens.

    Returns the caller's Principal (session 22): the cookie and role-less tokens are the athlete;
    a `role="coach"` token is a coach, which `call_tool` restricts to the coaching tools.

    Public deployment: a Supabase access token (the web app) or a device token resolved to the user who
    minted it. Either way the request's tenant is set here, from the verified identity."""
    if tenant.is_public():
        raw = _bearer(request)
        if raw and _looks_like_jwt(raw):
            claims = await _authenticate_jwt(raw)
            return athlete_for(claims.sub)
        if raw:
            resolved = await run_in_threadpool(device_tokens.resolve, db, hash_token(raw))
            if resolved is not None:
                tenant.set_owner(resolved.owner_id)
                await run_in_threadpool(device_tokens.touch, db, resolved)
                return principal_from_token(hash_token(raw), resolved.role, resolved.display_name, resolved.owner_id)
        raise HTTPException(status_code=401, detail="Not authenticated")
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
                return principal_from_token(row.token_hash, row.role, row.display_name)
    raise HTTPException(status_code=401, detail="Not authenticated")


async def require_tool_auth(request: Request, db: Session = Depends(get_db)) -> Principal:
    """Athlete-only bearer access: a coach-role token is refused (403), so a route that adopts
    this dependency can never hand a coach's token the athlete's data by accident."""
    principal = await _tool_principal(request, db)
    if not principal.is_athlete:
        raise HTTPException(status_code=403, detail="This token's role can't use this endpoint")
    return principal


async def require_tool_auth_allow_coach(request: Request, db: Session = Depends(get_db)) -> Principal:
    """The explicit opt-in: only the shared tool endpoints use it, and `call_tool` then restricts a
    coach principal to the coaching tools."""
    return await _tool_principal(request, db)
