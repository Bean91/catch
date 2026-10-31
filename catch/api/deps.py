from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from fastapi import HTTPException, Request
from sqlmodel import Session

from catch.core.db import engine
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
