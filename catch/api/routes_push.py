from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from catch.api.deps import get_db, require_auth
from catch.core.config import settings
from catch.core.models import NotificationLog, PushSubscription
from catch.notify import push

router = APIRouter(dependencies=[Depends(require_auth)])


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


@router.get("/api/push/vapid-public-key")
def vapid_public_key():
    # Served at runtime rather than baked into the built bundle (task Part A.1) — the laptop
    # that runs `npm run build` doesn't necessarily have the Pi's real .env, and rotating the
    # key would otherwise need a rebuild+redeploy instead of just an env change + restart.
    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Push notifications aren't configured (no VAPID_PUBLIC_KEY)")
    return {"public_key": settings.vapid_public_key}


@router.post("/api/push/subscribe")
def subscribe(body: SubscribeRequest = Body(...), db: Session = Depends(get_db)):
    row = db.exec(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)).first()
    if row is None:
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
def list_subscriptions(db: Session = Depends(get_db)):
    rows = db.exec(select(PushSubscription).order_by(PushSubscription.created_at)).all()
    return rows


@router.post("/api/push/test")
def send_test(body: TestSendRequest = Body(...), db: Session = Depends(get_db)):
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


@router.get("/api/push/log")
def notification_log(db: Session = Depends(get_db)):
    rows = db.exec(select(NotificationLog).order_by(NotificationLog.sent_at.desc()).limit(50)).all()
    return rows
