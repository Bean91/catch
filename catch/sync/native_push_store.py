"""Session 30 (docs/mobile/push.md): the ONLY module that reads or writes `native_push_tokens`.

The table is global (catch_api-only) so a device token can belong to one account at a time; every function therefore takes the
acting owner explicitly and filters by it. Nothing here needs raw SQL."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete as sa_delete
from sqlmodel import func, select

from catch.core.models import NativePushToken
from catch.sync.leaderboard_store import StoreError, store

MAX_TOKENS_PER_USER = 10
PLATFORMS = ("apns", "fcm")
ENVIRONMENTS = ("sandbox", "production")
MAX_TOKEN_CHARS = 4096  # an FCM registration token is ~163 chars, an APNs device token 64 hex; both far under this


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _view(t: NativePushToken) -> dict:
    # The full token never leaves the server again after it's stored: a device recognises its own row by the last characters.
    return {"id": t.id, "kind": "native", "platform": t.platform, "endpoint": f"native:{t.platform}", "label": t.label, "token_hint": t.token[-8:],
            "environment": t.environment, "created_at": t.created_at, "last_seen_at": t.last_seen_at}


def register(owner_id: str, *, platform: str, token: str, environment: str, app_id: str, label: Optional[str]) -> dict:
    if platform not in PLATFORMS:
        raise StoreError("Unknown push platform", 422)
    if environment not in ENVIRONMENTS:
        raise StoreError("Unknown push environment", 422)
    if not token or len(token) > MAX_TOKEN_CHARS or any(ord(c) <= 32 for c in token):
        raise StoreError("Not a valid push token", 422)
    if not app_id or len(app_id) > 200 or len(label or "") > 80:
        raise StoreError("Registration fields are too long", 422)
    with store() as s:
        row = s.exec(select(NativePushToken).where(NativePushToken.platform == platform, NativePushToken.token == token)).first()
        if row is None:
            if s.exec(select(func.count()).select_from(NativePushToken).where(NativePushToken.owner_id == owner_id)).one() >= MAX_TOKENS_PER_USER:
                raise StoreError("Too many devices are registered. Remove one first.", 409)
            row = NativePushToken(owner_id=owner_id, platform=platform, token=token, environment=environment, app_id=app_id, label=label)
            s.add(row)
        else:
            # Same handset, possibly a different account now: the token moves, so the previous account stops receiving on it.
            row.owner_id = owner_id
            row.environment = environment
            row.app_id = app_id
            if label is not None:
                row.label = label
            row.last_seen_at = _now()
        s.commit()
        s.refresh(row)
        return _view(row)


def unregister(owner_id: str, *, platform: str, token: str) -> None:
    with store() as s:
        s.exec(sa_delete(NativePushToken).where(NativePushToken.owner_id == owner_id, NativePushToken.platform == platform, NativePushToken.token == token))
        s.commit()


def list_for(owner_id: str) -> list[dict]:
    with store() as s:
        rows = s.exec(select(NativePushToken).where(NativePushToken.owner_id == owner_id).order_by(NativePushToken.created_at)).all()
        return [_view(r) for r in rows]


def tokens_for(owner_id: str) -> list[NativePushToken]:
    """Full rows, for the sender only. Detached copies, safe to use after the store session closes."""
    with store() as s:
        rows = s.exec(select(NativePushToken).where(NativePushToken.owner_id == owner_id)).all()
        for r in rows:
            s.expunge(r)
        return list(rows)


def get_for(owner_id: str, token_id: int) -> Optional[NativePushToken]:
    with store() as s:
        row = s.get(NativePushToken, token_id)
        if row is None or row.owner_id != owner_id:
            return None
        s.expunge(row)
        return row


def prune(token_id: int) -> None:
    with store() as s:
        s.exec(sa_delete(NativePushToken).where(NativePushToken.id == token_id))
        s.commit()


def flip_environment(token_id: int, environment: str) -> None:
    with store() as s:
        row = s.get(NativePushToken, token_id)
        if row is not None:
            row.environment = environment
            s.commit()


def delete_owner_data(owner_id: str) -> None:
    with store() as s:
        s.exec(sa_delete(NativePushToken).where(NativePushToken.owner_id == owner_id))
        s.commit()
