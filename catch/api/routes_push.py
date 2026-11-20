from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from catch.api.deps import get_db, require_auth
from catch.coach import limits
from catch.core import netguard, tenant
from catch.core.config import settings
from catch.core.owner import current_owner_id
from catch.core.models import NotificationLog, PushSubscription
from catch.notify import native_push, push
from catch.sync import native_push_store
from catch.sync.leaderboard_store import StoreError

router = APIRouter(dependencies=[Depends(require_auth)])

MAX_SUBSCRIPTIONS_PER_USER = 10
MAX_FIELD_CHARS = 256


def _throttle(owner_id: str) -> None:
    try:
        limits.check_rate(owner_id, "push")
    except limits.LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.message) from None


class SubscribeKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: SubscribeKeys
    label: str | None = None
    user_agent: str | None = None


class UnsubscribeRequest(BaseModel):
    endpoint: str


class TestSendRequest(BaseModel):
    subscription_id: int
    kind: str = "web"  # "native" = a store-app registration (session 30)


class NativeSubscribeRequest(BaseModel):
    platform: str
    token: str
    environment: str = "production"
    app_id: str
    label: str | None = None


class NativeUnsubscribeRequest(BaseModel):
    platform: str
    token: str


@router.get("/api/push/vapid-public-key")
def vapid_public_key():
    # Served at runtime rather than baked into the built bundle (task Part A.1) — the laptop
    # that runs `npm run build` doesn't necessarily have the Pi's real .env, and rotating the
    # key would otherwise need a rebuild+redeploy instead of just an env change + restart.
    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Push notifications aren't configured (no VAPID_PUBLIC_KEY)")
    return {"public_key": settings.vapid_public_key}


@router.post("/api/push/subscribe")
def subscribe(body: SubscribeRequest = Body(...), db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    _throttle(owner_id)
    try:
        netguard.validate_push_endpoint(body.endpoint)
    except netguard.UnsafeUrl as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if max(len(body.keys.p256dh), len(body.keys.auth)) > MAX_FIELD_CHARS or len(body.label or "") > 80 or len(body.user_agent or "") > 300:
        raise HTTPException(status_code=400, detail="Subscription fields are too long")
    row = db.exec(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)).first()
    if row is None:
        if len(db.exec(select(PushSubscription)).all()) >= MAX_SUBSCRIPTIONS_PER_USER:
            raise HTTPException(status_code=409, detail="Too many devices are registered. Remove one first.")
        row = PushSubscription(endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth)
        db.add(row)
    else:
        row.p256dh = body.keys.p256dh
        row.auth = body.keys.auth
    if body.label is not None:
        row.label = body.label
    if body.user_agent is not None:
        row.user_agent = body.user_agent
    row.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/api/push/subscribe")
def unsubscribe(body: UnsubscribeRequest = Body(...), db: Session = Depends(get_db)):
    row = db.exec(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)).first()
    if row is not None:
        db.delete(row)
        db.commit()
    return {"deleted": True}


@router.get("/api/push/subscriptions")
def list_subscriptions(db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    rows = db.exec(select(PushSubscription).order_by(PushSubscription.created_at)).all()
    if not tenant.is_public():
        return rows
    web = [{"id": r.id, "kind": "web", "endpoint": r.endpoint, "label": r.label, "created_at": r.created_at, "last_seen_at": r.last_seen_at} for r in rows]
    return web + native_push_store.list_for(owner_id)


def _native_only() -> None:
    if not tenant.is_public():
        raise HTTPException(status_code=404, detail="Not found")  # the store apps exist for the public deployment only


@router.post("/api/push/native/subscribe")
def native_subscribe(body: NativeSubscribeRequest = Body(...), owner_id: str = Depends(current_owner_id)):
    _native_only()
    _throttle(owner_id)
    try:
        return native_push_store.register(owner_id, platform=body.platform, token=body.token, environment=body.environment, app_id=body.app_id, label=body.label)
    except StoreError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@router.delete("/api/push/native/subscribe")
def native_unsubscribe(body: NativeUnsubscribeRequest = Body(...), owner_id: str = Depends(current_owner_id)):
    _native_only()
    native_push_store.unregister(owner_id, platform=body.platform, token=body.token)
    return {"deleted": True}


@router.post("/api/push/test")
def send_test(body: TestSendRequest = Body(...), db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    _throttle(owner_id)
    if body.kind == "native":
        _native_only()
        return _send_native_test(owner_id, body.subscription_id)
    sub = db.get(PushSubscription, body.subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="No such subscription")
    try:
        sent, should_prune = push.send_to_subscription(
            sub, {"title": "Catch", "body": "Test notification — if you can see this, it worked.", "url": "/settings", "type": "test"}
        )
    except push.PushNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    if should_prune:
        db.delete(sub)
    db.add(NotificationLog(type="test", title="Catch", body="Test notification", device_count=1 if sent else 0))
    db.commit()
    if not sent:
        raise HTTPException(status_code=502, detail="Push service did not accept the notification")
    return {"sent": True}


def _send_native_test(owner_id: str, token_id: int):
    row = native_push_store.get_for(owner_id, token_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such subscription")
    if not native_push.configured_for(row.platform):
        raise HTTPException(status_code=503, detail="Push to the phone app isn't configured on the server yet")
    sent, prune = native_push.send_to_token(
        row, {"title": "Catch", "body": "Test notification — if you can see this, it worked.", "url": "/settings", "type": "test"},
        on_environment_fix=lambda env: native_push_store.flip_environment(row.id, env),
    )
    if prune:
        native_push_store.prune(row.id)
    if not sent:
        raise HTTPException(status_code=502, detail="Push service did not accept the notification")
    return {"sent": True}


@router.get("/api/push/log")
def notification_log(db: Session = Depends(get_db)):
    rows = db.exec(select(NotificationLog).order_by(NotificationLog.sent_at.desc()).limit(50)).all()
    return rows
