from __future__ import annotations

import dataclasses

from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_push_endpoints_require_auth(client):
    assert client.get("/api/push/vapid-public-key").status_code == 401
    assert client.get("/api/push/subscriptions").status_code == 401
    assert client.post("/api/push/subscribe", json={}).status_code == 401


def test_vapid_public_key_503_when_unconfigured(client, monkeypatch):
    _login(client)
    import catch.api.routes_push as routes_push

    monkeypatch.setattr(routes_push, "settings", dataclasses.replace(routes_push.settings, vapid_public_key=""))
    resp = client.get("/api/push/vapid-public-key")
    assert resp.status_code == 503


def test_vapid_public_key_returned_when_configured(client, monkeypatch):
    _login(client)
    import catch.api.routes_push as routes_push

    monkeypatch.setattr(routes_push, "settings", dataclasses.replace(routes_push.settings, vapid_public_key="fake-pub-key"))
    resp = client.get("/api/push/vapid-public-key")
    assert resp.status_code == 200
    assert resp.json() == {"public_key": "fake-pub-key"}


def test_subscribe_then_list_then_unsubscribe(client):
    _login(client)
    resp = client.post(
        "/api/push/subscribe",
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
            "keys": {"p256dh": "p256dh-value", "auth": "auth-value"},
            "label": "My iPhone",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "My iPhone"

    listing = client.get("/api/push/subscriptions")
    assert len(listing.json()) == 1
    assert listing.json()[0]["label"] == "My iPhone"

    # Re-subscribing the same endpoint updates in place, not a duplicate row.
    client.post(
        "/api/push/subscribe",
        json={"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "new-p256dh", "auth": "new-auth"}, "label": "My iPhone"},
    )
    assert len(client.get("/api/push/subscriptions").json()) == 1

    resp = client.request("DELETE", "/api/push/subscribe", json={"endpoint": "https://fcm.googleapis.com/fcm/send/abc"})
    assert resp.status_code == 200
    assert client.get("/api/push/subscriptions").json() == []


def test_send_test_push_prunes_on_410_and_reports_failure(client, monkeypatch):
    _login(client)
    import catch.api.routes_push as routes_push

    sub = client.post(
        "/api/push/subscribe",
        json={"endpoint": "https://fcm.googleapis.com/fcm/send/gone", "keys": {"p256dh": "a", "auth": "b"}},
    ).json()

    # send_to_subscription itself is round-trip-tested against real crypto in
    # tests/notify/test_push.py — here only routes_push's own prune-on-should_prune and
    # 502-on-not-sent wiring is under test, so it's mocked directly rather than needing a
    # realistic (valid EC point) p256dh/auth pair.
    monkeypatch.setattr(routes_push.push, "send_to_subscription", lambda sub, payload: (False, True))

    resp = client.post("/api/push/test", json={"subscription_id": sub["id"]})
    assert resp.status_code == 502
    assert client.get("/api/push/subscriptions").json() == []  # pruned


def test_send_test_push_unconfigured_returns_503(client, monkeypatch):
    _login(client)
    from catch.notify import push as push_module

    # Explicitly blanked rather than relying on the ambient environment having no VAPID
    # keys — this laptop's real .env has them set (session 16 generated them), which would
    # otherwise make this test flaky across machines.
    monkeypatch.setattr(push_module, "settings", dataclasses.replace(push_module.settings, vapid_private_key=""))
    sub = client.post(
        "/api/push/subscribe",
        json={"endpoint": "https://fcm.googleapis.com/fcm/send/x", "keys": {"p256dh": "a", "auth": "b"}},
    ).json()

    resp = client.post("/api/push/test", json={"subscription_id": sub["id"]})
    assert resp.status_code == 503


def test_send_test_push_unknown_subscription_404s(client):
    _login(client)
    resp = client.post("/api/push/test", json={"subscription_id": 999})
    assert resp.status_code == 404


def test_subscribe_refuses_endpoints_that_are_not_push_services(client):
    _login(client)
    for url in ["http://fcm.googleapis.com/x", "https://169.254.169.254/latest", "https://127.0.0.1/x", "https://evil.example.com/x"]:
        resp = client.post("/api/push/subscribe", json={"endpoint": url, "keys": {"p256dh": "a", "auth": "b"}})
        assert resp.status_code == 400, url
    assert client.get("/api/push/subscriptions").json() == []


def test_subscriptions_per_user_are_capped(client):
    _login(client)
    import catch.api.routes_push as routes_push
    from catch.coach import limits

    limits.BUCKET_LIMITS["push"] = 1000
    try:
        for i in range(routes_push.MAX_SUBSCRIPTIONS_PER_USER):
            ok = client.post("/api/push/subscribe", json={"endpoint": f"https://fcm.googleapis.com/fcm/send/{i}", "keys": {"p256dh": "a", "auth": "b"}})
            assert ok.status_code == 200
        over = client.post("/api/push/subscribe", json={"endpoint": "https://fcm.googleapis.com/fcm/send/over", "keys": {"p256dh": "a", "auth": "b"}})
        assert over.status_code == 409
    finally:
        limits.BUCKET_LIMITS["push"] = 10


def test_push_routes_are_throttled(client):
    _login(client)
    from catch.coach import limits

    limits._windows.clear()
    codes = [
        client.post("/api/push/subscribe", json={"endpoint": "https://fcm.googleapis.com/fcm/send/t", "keys": {"p256dh": "a", "auth": "b"}}).status_code
        for _ in range(12)
    ]
    assert 429 in codes
    limits._windows.clear()
