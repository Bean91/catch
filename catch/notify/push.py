from __future__ import annotations

import base64
import json
import logging
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from catch.core.config import settings
from catch.core.models import NotificationLog, PushSubscription

logger = logging.getLogger("catch.notify.push")

# `py_vapid`/`http_ece` are lazy-imported (below) — pure-Python, no ARM concern, but a Pi that
# never sets VAPID_* env vars shouldn't pay even an import cost for a feature it never uses.


class PushNotConfigured(RuntimeError):
    pass


def _b64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def _encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    import http_ece
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import ec

    receiver_raw = _b64url_decode(p256dh)
    auth_raw = _b64url_decode(auth)
    # A fresh ephemeral ECDH keypair per message (RFC 8291) — never reused, never stored.
    server_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    return http_ece.encrypt(payload, private_key=server_key, dh=receiver_raw, auth_secret=auth_raw, version="aes128gcm")


def _vapid_headers(endpoint: str) -> dict[str, str]:
    from py_vapid import Vapid02

    vapid = Vapid02.from_raw(settings.vapid_private_key.encode())
    parsed = urlparse(endpoint)
    aud = f"{parsed.scheme}://{parsed.netloc}"
    # Vapid02 (RFC 8292 "vapid" scheme) — what every major push service (web.push.apple.com,
    # fcm.googleapis.com, Mozilla's autopush) expects today; the older Vapid01 "WebPush" scheme
    # this library also supports is for Draft-01-only push services, none of which this app
    # talks to.
    return vapid.sign({"aud": aud, "sub": settings.vapid_subject})


def send_to_subscription(sub: PushSubscription, payload: dict) -> tuple[bool, bool]:
    """Encrypts and POSTs `payload` to one subscription's push service. Returns
    `(sent, should_prune)` — `should_prune` is True only on a 404/410 (the subscription itself
    is gone, confirmed expired/revoked by the push service); every other failure (network,
    5xx, a misconfigured key) leaves the row alone, since none of those mean the device itself
    is at fault."""
    if not settings.vapid_private_key or not settings.vapid_public_key:
        raise PushNotConfigured("VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY are not set in .env")
    body = json.dumps(payload).encode()
    encrypted = _encrypt(body, sub.p256dh, sub.auth)
    headers = _vapid_headers(sub.endpoint)
    headers.update(
        {
            "Content-Type": "application/octet-stream",
            "Content-Encoding": "aes128gcm",
            # 24h: long enough to deliver a morning brief to a phone that was off overnight,
            # short enough that a stale "sync broken" alert doesn't resurface days later.
            "TTL": "86400",
            "Urgency": "normal",
        }
    )
    try:
        resp = httpx.post(sub.endpoint, content=encrypted, headers=headers, timeout=10.0)
    except httpx.HTTPError:
        logger.exception("push send failed (network) for subscription id=%s", sub.id)
        return False, False
    if resp.status_code in (404, 410):
        return False, True
    if resp.status_code >= 400:
        logger.warning("push send failed status=%s for subscription id=%s", resp.status_code, sub.id)
        return False, False
    return True, False


def notify(session: Session, *, type: str, title: str, body: str, deep_link: str | None = None) -> int:
    """Sends to every registered device, prunes any subscription the push service confirms is
    gone, and always writes one `NotificationLog` row (task Part A.4) — even with zero devices
    registered or Web Push unconfigured, since a caller (catch/notify/triggers.py's dedup
    logic) still needs that row to exist to know "already sent today" for the right type.
    Returns how many devices actually received it."""
    sent_count = 0
    if settings.vapid_private_key and settings.vapid_public_key:
        payload = {"title": title, "body": body, "url": deep_link or "/", "type": type}
        for sub in session.exec(select(PushSubscription)).all():
            sent, should_prune = send_to_subscription(sub, payload)
            if sent:
                sent_count += 1
            if should_prune:
                session.delete(sub)
    session.add(NotificationLog(type=type, title=title, body=body, deep_link=deep_link, device_count=sent_count))
    session.commit()
    return sent_count
