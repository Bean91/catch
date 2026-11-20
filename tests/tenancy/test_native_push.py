"""Session 30 (docs/mobile/push.md): native token registration, the one-account-per-device rule, and APNs/FCM delivery against
mock transports (no live call; the suite's live-call guard would refuse one anyway)."""

from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
import jwt

from catch.core import config
from catch.core.models import NativePushToken
from catch.notify import native_push
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A, B = bearer(kit.ALICE), bearer(kit.BOB)
TOKEN = "a" * 64


def _reg(client, headers, token=TOKEN, platform="apns", **kw):
    body = {"platform": platform, "token": token, "environment": "production", "app_id": "com.openoted.catch", "label": "iPhone", **kw}
    return client.post("/api/push/native/subscribe", headers=headers, json=body)


def test_register_list_and_unregister_never_reveals_the_whole_token(pub_client):
    pub_client.get("/api/me", headers=A)
    r = _reg(pub_client, A)
    assert r.status_code == 200, r.text
    assert r.json()["token_hint"] == TOKEN[-8:] and TOKEN not in r.text
    rows = pub_client.get("/api/push/subscriptions", headers=A).json()
    assert [x["kind"] for x in rows] == ["native"] and TOKEN not in json.dumps(rows)
    assert pub_client.request("DELETE", "/api/push/native/subscribe", headers=A, json={"platform": "apns", "token": TOKEN}).json() == {"deleted": True}
    assert pub_client.get("/api/push/subscriptions", headers=A).json() == []


def test_a_token_belongs_to_one_account_the_next_person_to_register_it_takes_it(pub_client):
    pub_client.get("/api/me", headers=A)
    pub_client.get("/api/me", headers=B)
    assert _reg(pub_client, A).status_code == 200
    assert pub_client.get("/api/push/subscriptions", headers=A).json() != []
    assert _reg(pub_client, B).status_code == 200  # same handset, someone else signed in
    assert pub_client.get("/api/push/subscriptions", headers=A).json() == []
    assert len(pub_client.get("/api/push/subscriptions", headers=B).json()) == 1


def test_one_person_cannot_unregister_anothers_token(pub_client):
    pub_client.get("/api/me", headers=A)
    pub_client.get("/api/me", headers=B)
    _reg(pub_client, A)
    pub_client.request("DELETE", "/api/push/native/subscribe", headers=B, json={"platform": "apns", "token": TOKEN})
    assert len(pub_client.get("/api/push/subscriptions", headers=A).json()) == 1


@pytest.mark.parametrize("bad", [{"platform": "web"}, {"environment": "staging"}, {"token": ""}, {"token": "has space"}, {"token": "x" * 5000}, {"app_id": ""}])
def test_bad_registrations_are_refused(pub_client, bad):
    pub_client.get("/api/me", headers=A)
    assert _reg(pub_client, A, **bad).status_code in (400, 422)


def test_a_device_cap_applies(pub_client):
    from catch.sync import native_push_store

    pub_client.get("/api/me", headers=A)
    for i in range(10):  # direct, so the per-minute route throttle isn't what this test measures
        native_push_store.register(kit.ALICE, platform="apns", token=f"{i:064d}", environment="production", app_id="com.openoted.catch", label=None)
    assert _reg(pub_client, A, token="f" * 64).status_code == 409


def test_native_routes_do_not_exist_on_the_personal_deployment(client):
    assert client.post("/api/push/native/subscribe", json={"platform": "apns", "token": TOKEN, "environment": "production", "app_id": "x"}).status_code in (401, 404)


# ---------------------------------------------------------------- senders

def _apns_key_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


@pytest.fixture()
def apns(monkeypatch):
    for k, v in {"apns_key_p8": _apns_key_pem(), "apns_key_id": "KEYID12345", "apns_team_id": "TEAM123456", "apns_topic": "com.openoted.catch"}.items():
        monkeypatch.setattr(config.settings, k, v, raising=False) if False else object.__setattr__(config.settings, k, v)
    native_push.reset_caches()
    yield
    for k in ("apns_key_p8", "apns_key_id", "apns_team_id"):
        object.__setattr__(config.settings, k, "")
    native_push.reset_caches()


def _client(handler, monkeypatch):
    monkeypatch.setattr(native_push, "_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def _row(platform="apns", env="production", token=TOKEN):
    return NativePushToken(id=7, owner_id="o", platform=platform, token=token, environment=env, app_id="com.openoted.catch")


PAYLOAD = {"title": "Morning brief", "body": "Recovery 82", "url": "/calendar/events/3", "type": "morning_brief"}


def test_apns_request_shape_and_provider_token(apns, monkeypatch):
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["headers"], seen["body"] = str(req.url), req.headers, json.loads(req.content)
        return httpx.Response(200)

    _client(handler, monkeypatch)
    assert native_push.send_apns(_row(), PAYLOAD) == (True, False)
    assert seen["url"] == f"https://api.push.apple.com/3/device/{TOKEN}"
    assert seen["headers"]["apns-topic"] == "com.openoted.catch" and seen["headers"]["apns-push-type"] == "alert"
    assert seen["headers"]["apns-collapse-id"] == "morning_brief"
    assert seen["body"]["aps"]["alert"] == {"title": "Morning brief", "body": "Recovery 82"} and seen["body"]["url"] == "/calendar/events/3"
    token = seen["headers"]["authorization"].removeprefix("bearer ")
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == "TEAM123456" and jwt.get_unverified_header(token) == {"typ": "JWT", "alg": "ES256", "kid": "KEYID12345"}


def test_sandbox_registration_goes_to_the_sandbox_host(apns, monkeypatch):
    urls = []
    _client(lambda req: (urls.append(str(req.url)), httpx.Response(200))[1], monkeypatch)
    native_push.send_apns(_row(env="sandbox"), PAYLOAD)
    assert urls[0].startswith("https://api.sandbox.push.apple.com/")


def test_a_bad_device_token_on_one_host_is_retried_on_the_other_and_remembered(apns, monkeypatch):
    def handler(req):
        return httpx.Response(200) if req.url.host == "api.sandbox.push.apple.com" else httpx.Response(400, json={"reason": "BadDeviceToken"})

    _client(handler, monkeypatch)
    fixed = []
    assert native_push.send_apns(_row(env="production"), PAYLOAD, on_environment_fix=fixed.append) == (True, False)
    assert fixed == ["sandbox"]


@pytest.mark.parametrize("status, body, expected", [
    (410, {"reason": "Unregistered"}, (False, True)),
    (400, {"reason": "BadDeviceToken"}, (False, True)),
    (403, {"reason": "ExpiredProviderToken"}, (False, False)),  # our credential, never the device's fault
    (429, {"reason": "TooManyRequests"}, (False, False)),
    (503, {"reason": "ServiceUnavailable"}, (False, False)),
])
def test_apns_failures_prune_only_when_the_token_itself_is_dead(apns, monkeypatch, status, body, expected):
    _client(lambda req: httpx.Response(status, json=body), monkeypatch)
    assert native_push.send_apns(_row(), PAYLOAD) == expected


def test_a_network_error_never_prunes(apns, monkeypatch):
    def boom(req):
        raise httpx.ConnectError("down")

    _client(boom, monkeypatch)
    assert native_push.send_apns(_row(), PAYLOAD) == (False, False)


def test_nothing_is_sent_without_credentials():
    object.__setattr__(config.settings, "apns_key_p8", "")
    assert native_push.send_apns(_row(), PAYLOAD) == (False, False)
    assert native_push.configured_for("apns") is False and native_push.configured_for("fcm") is False


@pytest.fixture()
def fcm():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    object.__setattr__(config.settings, "fcm_service_account_json", json.dumps({"client_email": "svc@proj.iam.gserviceaccount.com", "private_key": pem, "project_id": "catch-proj"}))
    native_push.reset_caches()
    yield key.public_key()
    object.__setattr__(config.settings, "fcm_service_account_json", "")
    native_push.reset_caches()


def test_fcm_exchanges_a_signed_assertion_then_sends_a_v1_message(fcm, monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        if req.url.host == "oauth2.googleapis.com":
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            claims = jwt.decode(form["assertion"].replace("%2E", "."), fcm, algorithms=["RS256"], audience="https://oauth2.googleapis.com/token")
            assert claims["iss"] == "svc@proj.iam.gserviceaccount.com" and "firebase.messaging" in claims["scope"]
            return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600})
        body = json.loads(req.content)
        assert req.url.path == "/v1/projects/catch-proj/messages:send" and req.headers["authorization"] == "Bearer ya29.test"
        assert body["message"]["token"] == "t" * 100 and body["message"]["data"] == {"url": "/calendar/events/3", "type": "morning_brief"}
        return httpx.Response(200, json={"name": "x"})

    _client(handler, monkeypatch)
    assert native_push.send_fcm(_row("fcm", token="t" * 100), PAYLOAD) == (True, False)
    assert native_push.send_fcm(_row("fcm", token="t" * 100), PAYLOAD) == (True, False)
    assert [c.url.host for c in calls].count("oauth2.googleapis.com") == 1  # the access token is cached


def test_fcm_prunes_an_unregistered_token_and_keeps_one_it_could_not_send(fcm, monkeypatch):
    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "x", "expires_in": 3600})
        return httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})

    _client(handler, monkeypatch)
    assert native_push.send_fcm(_row("fcm", token="t" * 100), PAYLOAD) == (False, True)
    _client(lambda req: httpx.Response(200, json={"access_token": "x", "expires_in": 3600}) if req.url.host == "oauth2.googleapis.com" else httpx.Response(500), monkeypatch)
    assert native_push.send_fcm(_row("fcm", token="t" * 100), PAYLOAD) == (False, False)


def test_only_fixed_push_hosts_are_ever_called():
    from catch.core import netguard

    for url in ("https://evil.example.com/3/device/x", "http://api.push.apple.com/x", "https://api.push.apple.com.evil.com/x", "https://user@api.push.apple.com/x", "https://api.push.apple.com:8443/x"):
        with pytest.raises(netguard.UnsafeUrl):
            netguard.assert_native_push_host(url)
    assert netguard.assert_native_push_host("https://fcm.googleapis.com/v1/projects/p/messages:send")


def test_notify_reaches_a_native_token_even_when_vapid_is_unset_and_prunes_a_dead_one(pub_client, apns, monkeypatch):
    from sqlmodel import Session

    from catch.core import tenant
    from catch.notify import push

    pub_client.get("/api/me", headers=A)
    _reg(pub_client, A)
    _reg(pub_client, A, token="b" * 64)
    seen = []

    def handler(req: httpx.Request):
        seen.append(str(req.url))
        return httpx.Response(410, json={"reason": "Unregistered"}) if "b" * 64 in str(req.url) else httpx.Response(200)

    _client(handler, monkeypatch)
    object.__setattr__(config.settings, "vapid_private_key", "")
    from catch.core import db as db_module

    with tenant.use_owner(kit.ALICE), Session(db_module.engine) as s:
        sent = push.notify(s, type="morning_brief", title="t", body="b", deep_link="/")
    assert sent == 1 and len(seen) == 2
    assert len(pub_client.get("/api/push/subscriptions", headers=A).json()) == 1


def test_deleting_an_account_removes_its_tokens(pub_client):
    from catch.sync import native_push_store

    pub_client.get("/api/me", headers=A)
    _reg(pub_client, A)
    native_push_store.delete_owner_data(kit.ALICE)
    assert pub_client.get("/api/push/subscriptions", headers=A).json() == []
