"""Session 28 log/response review as tests: plant a sentinel secret in each place a credential, token or capability URL could
travel through a failure path, then assert it appears in no log record, no response body and nothing persisted."""

from __future__ import annotations

import logging

import httpx
import pytest
from sqlmodel import Session, select

from catch.api import routes_account
from catch.core import redact
from catch.core.models import ProviderConnection
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A = bearer(kit.ALICE)
KEY = "alice-garmin-personal-key-SENTINEL1234567890"
SERVICE_KEY = "sb_secret_SENTINELservicekey0123456789abcdef"
FCM_PATH = "fcm/send/SENTINEL-capability-token-0123456789"


@pytest.fixture(autouse=True)
def _scrub_logs():
    redact.install_log_filter()


def _everything(caplog) -> str:
    return "\n".join(r.getMessage() + (str(r.exc_text) if r.exc_text else "") for r in caplog.records)


def test_a_provider_failure_that_echoes_the_key_leaks_it_nowhere(pub_client, pub_engine, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    pub_client.get("/api/me", headers=A)

    def post(url, headers=None, timeout=None):
        return httpx.Response(401, text=f"bad key {KEY} for {url}?api_key={KEY}", request=httpx.Request("POST", url))

    monkeypatch.setattr("catch.sync.garmin_client.httpx.post", post)
    resp = pub_client.put("/api/connections/garmin/credential", headers=A, json={"api_key": KEY})
    assert KEY not in resp.text and KEY not in _everything(caplog)
    with Session(pub_engine) as s:
        rows = s.execute(select(ProviderConnection).execution_options(tenant_unscoped=True)).scalars().all()
        assert all(KEY not in repr(r.__dict__) for r in rows)


def test_a_validation_error_on_the_credential_route_does_not_echo_the_body(pub_client, caplog):
    caplog.set_level(logging.DEBUG)
    pub_client.get("/api/me", headers=A)
    resp = pub_client.put("/api/connections/garmin/credential", headers=A, json={"apikey": KEY})
    assert resp.status_code == 422 and KEY not in resp.text and KEY not in _everything(caplog)


def test_an_oauth_callback_with_a_bad_state_logs_and_returns_no_code(pub_client, caplog):
    caplog.set_level(logging.DEBUG)
    resp = pub_client.get("/auth/whoop/callback", params={"code": "SENTINELauthcode0123456789", "state": "x"}, follow_redirects=False)
    assert "SENTINELauthcode" not in resp.text and "SENTINELauthcode" not in resp.headers.get("location", "")
    assert "SENTINELauthcode" not in _everything(caplog)


def test_a_failed_auth_admin_call_does_not_log_the_service_key(caplog, monkeypatch):
    import dataclasses

    from fastapi import HTTPException

    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(routes_account, "settings", dataclasses.replace(routes_account.settings, supabase_secret_key=SERVICE_KEY, supabase_url="http://auth.invalid"))
    monkeypatch.setattr(routes_account.httpx, "request", lambda *a, **k: httpx.Response(500, text=f"upstream said apikey {SERVICE_KEY}", request=httpx.Request("DELETE", "http://auth.invalid")))
    with pytest.raises(HTTPException) as exc:
        routes_account.admin_delete_auth_user(kit.ALICE)
    assert SERVICE_KEY not in str(exc.value.detail) and SERVICE_KEY not in _everything(caplog)


def test_a_push_network_failure_does_not_log_the_capability_url(caplog, monkeypatch):
    from catch.core import config
    from catch.core.models import PushSubscription
    from catch.notify import push

    caplog.set_level(logging.DEBUG)
    endpoint = f"https://fcm.googleapis.com/{FCM_PATH}"
    monkeypatch.setattr(push, "settings", __import__("dataclasses").replace(config.settings, vapid_private_key="x", vapid_public_key="y"))
    monkeypatch.setattr(push, "_encrypt", lambda *a: b"x")
    monkeypatch.setattr(push, "_vapid_headers", lambda e: {})

    def boom(url, **kw):
        raise httpx.ConnectError(f"cannot reach {url}")

    monkeypatch.setattr(push.httpx, "post", boom)
    sent, prune = push.send_to_subscription(PushSubscription(id=1, endpoint=endpoint, p256dh="a", auth="b"), {"t": 1})
    assert (sent, prune) == (False, False)
    assert "SENTINEL-capability" not in _everything(caplog)
