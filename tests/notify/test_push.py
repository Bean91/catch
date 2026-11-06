from __future__ import annotations

import base64
import dataclasses
import json

import http_ece
import httpx
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid02
from sqlmodel import select

from catch.core.models import NotificationLog, PushSubscription
from catch.notify import push


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _fake_browser_subscription() -> tuple[PushSubscription, ec.EllipticCurvePrivateKey, bytes]:
    """A fake PushManager.subscribe() result — a receiver EC keypair + a 16-byte auth secret,
    exactly what a real browser would generate and return via subscription.getKey(...)."""
    receiver_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    receiver_pub_raw = receiver_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    auth_secret = b"\x11" * 16
    sub = PushSubscription(
        id=1,
        endpoint="https://web.push.apple.com/some-real-looking-path",
        p256dh=_b64url(receiver_pub_raw),
        auth=_b64url(auth_secret),
        label="Test iPhone",
    )
    return sub, receiver_key, auth_secret


@pytest.fixture()
def vapid_env(monkeypatch):
    vapid = Vapid02()
    vapid.generate_keys()
    priv_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    pub_raw = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    monkeypatch.setattr(
        push,
        "settings",
        dataclasses.replace(
            push.settings,
            vapid_private_key=_b64url(priv_raw),
            vapid_public_key=_b64url(pub_raw),
            vapid_subject="mailto:test@example.com",
        ),
    )
    return vapid


def test_send_to_subscription_produces_a_message_the_real_browser_keys_can_decrypt(vapid_env, monkeypatch):
    """The whole point of RFC 8291 encryption is that only the holder of the subscription's
    *receiver* private key (which never leaves the browser) can read the payload — this proves
    the server side round-trips correctly without ever needing a real push service or a real
    browser, by playing the receiver's role ourselves."""
    sub, receiver_key, auth_secret = _fake_browser_subscription()

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(201)

    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, content, headers, timeout: httpx.Client(transport=httpx.MockTransport(handler)).post(
            url, content=content, headers=headers, timeout=timeout
        ),
    )

    sent, should_prune = push.send_to_subscription(sub, {"title": "Recovery 72%", "body": "Strain target 8-11", "url": "/"})

    assert sent is True
    assert should_prune is False

    req = captured["request"]
    assert req.headers["content-encoding"] == "aes128gcm"
    assert req.headers["ttl"] == "86400"
    assert req.headers["authorization"].startswith("vapid t=")
    assert "k=" in req.headers["authorization"]

    decrypted = http_ece.decrypt(req.content, private_key=receiver_key, auth_secret=auth_secret, version="aes128gcm")
    assert json.loads(decrypted) == {"title": "Recovery 72%", "body": "Strain target 8-11", "url": "/"}


@pytest.mark.parametrize("status", [404, 410])
def test_a_404_or_410_marks_the_subscription_for_pruning(vapid_env, monkeypatch, status):
    sub, _, _ = _fake_browser_subscription()
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, content, headers, timeout: httpx.Response(status, request=httpx.Request("POST", url)),
    )

    sent, should_prune = push.send_to_subscription(sub, {"title": "x", "body": "y"})

    assert sent is False
    assert should_prune is True


def test_a_server_error_does_not_mark_the_subscription_for_pruning(vapid_env, monkeypatch):
    sub, _, _ = _fake_browser_subscription()
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, content, headers, timeout: httpx.Response(503, request=httpx.Request("POST", url)),
    )

    sent, should_prune = push.send_to_subscription(sub, {"title": "x", "body": "y"})

    assert sent is False
    assert should_prune is False


def test_send_without_vapid_configured_raises(monkeypatch):
    monkeypatch.setattr(push, "settings", dataclasses.replace(push.settings, vapid_private_key=""))
    sub, _, _ = _fake_browser_subscription()

    with pytest.raises(push.PushNotConfigured):
        push.send_to_subscription(sub, {"title": "x", "body": "y"})


def test_notify_prunes_gone_subscriptions_and_always_logs(session, vapid_env, monkeypatch):
    sub, _, _ = _fake_browser_subscription()
    session.add(sub)
    session.commit()

    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, content, headers, timeout: httpx.Response(410, request=httpx.Request("POST", url)),
    )

    sent_count = push.notify(session, type="test", title="Hello", body="World", deep_link="/settings")

    assert sent_count == 0
    assert session.exec(select(PushSubscription)).all() == []
    logs = session.exec(select(NotificationLog)).all()
    assert len(logs) == 1
    assert logs[0].type == "test"
    assert logs[0].device_count == 0


def test_notify_with_no_vapid_configured_still_logs_with_zero_devices(session, monkeypatch):
    monkeypatch.setattr(push, "settings", dataclasses.replace(push.settings, vapid_private_key=""))

    sent_count = push.notify(session, type="morning_brief", title="Morning", body="72% recovery")

    assert sent_count == 0
    logs = session.exec(select(NotificationLog)).all()
    assert len(logs) == 1
