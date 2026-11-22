# Withings fixtures here are synthetic — built from the documented getmeas example and the
# standard meastype codes (see docs/withings-endpoints.md), not recorded from a live call,
# since completing real OAuth needs a browser. No live network calls in this file.
from __future__ import annotations

from catch.core import tenant
import dataclasses
import hashlib
import hmac as hmac_lib
from datetime import datetime, timedelta, timezone

import httpx

from catch.core.config import settings as real_settings
from catch.core.models import BodyComp, OAuthToken
from catch.sync import connections
from catch.sync import withings_client
from conftest import load_fixture

FAKE_SETTINGS = dataclasses.replace(
    real_settings,
    withings_client_id="test-client-id",
    withings_client_secret="test-client-secret",
    withings_redirect_uri="http://localhost:8000/auth/withings/callback",
)


def test_sign_matches_hmac_sha256(monkeypatch):
    monkeypatch.setattr(withings_client, "settings", FAKE_SETTINGS)
    expected = hmac_lib.new(b"test-client-secret", b"a,b,c", hashlib.sha256).hexdigest()
    assert withings_client._sign("a", "b", "c") == expected


def test_authorize_url_has_expected_params(monkeypatch):
    monkeypatch.setattr(withings_client, "settings", FAKE_SETTINGS)
    url = withings_client.authorize_url("my-state")
    assert url.startswith(withings_client.AUTHORIZE_URL)
    assert "client_id=test-client-id" in url
    assert "state=my-state" in url
    assert "scope=user.metrics" in url


def _resp(url: str, **kwargs) -> httpx.Response:
    # httpx.Response built by hand (not via a real transport round-trip) has no `.request`
    # attached, which raise_for_status() requires even on success — attach one.
    return httpx.Response(request=httpx.Request("POST", url), **kwargs)


def _fake_post_factory(token_body: dict):
    def fake_post(url, data=None, headers=None, timeout=None):
        if url == withings_client.SIGNATURE_URL:
            assert data["action"] == "getnonce"
            return _resp(url, status_code=200, json={"status": 0, "body": {"nonce": "fake-nonce"}})
        if url == withings_client.OAUTH_URL:
            assert data["nonce"] == "fake-nonce"
            assert "signature" in data
            assert "client_secret" not in data  # secret is the HMAC key, never sent as a value
            return _resp(url, status_code=200, json={"status": 0, "body": token_body})
        raise AssertionError(f"unexpected URL {url}")

    return fake_post


def test_exchange_code_stores_encrypted_tokens(monkeypatch, session):
    monkeypatch.setattr(withings_client, "settings", FAKE_SETTINGS)
    monkeypatch.setattr(
        withings_client.httpx,
        "post",
        _fake_post_factory(
            {
                "userid": "u1",
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 10800,
                "token_type": "Bearer",
            }
        ),
    )

    token = withings_client.exchange_code(session, "auth-code-123")
    assert token == "access-1"

    tokens = connections.oauth_tokens(session, "withings")
    assert (tokens.access, tokens.refresh) == ("access-1", "refresh-1")
    assert tokens.expires_at > datetime.now(timezone.utc) + timedelta(hours=2)
    assert session.get(OAuthToken, tenant.pk("withings")) is None


def test_refresh_rotates_refresh_token(monkeypatch, session):
    monkeypatch.setattr(withings_client, "settings", FAKE_SETTINGS)
    connections.store_oauth(session, "withings", access="old-access", refresh="old-refresh", expires_in=-60)

    monkeypatch.setattr(
        withings_client.httpx,
        "post",
        _fake_post_factory(
            {"userid": "u1", "access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 10800}
        ),
    )

    token = withings_client.get_access_token(session)
    assert token == "new-access"

    refreshed = connections.oauth_tokens(session, "withings")
    assert (refreshed.refresh, refreshed.access) == ("new-refresh", "new-access")


def test_sync_converts_values_and_maps_meastypes(monkeypatch, session):
    monkeypatch.setattr(withings_client, "settings", FAKE_SETTINGS)
    connections.store_oauth(session, "withings", access="valid-access", refresh="valid-refresh", expires_in=3600)

    fixture = load_fixture("withings", "getmeas_example.json")

    def fake_post(url, data=None, headers=None, timeout=None):
        assert url == withings_client.MEASURE_URL
        assert headers["Authorization"] == "Bearer valid-access"
        return _resp(url, status_code=200, json=fixture)

    monkeypatch.setattr(withings_client.httpx, "post", fake_post)

    n = withings_client.sync(session)
    assert n == 1

    rows = session.exec(__import__("sqlmodel").select(BodyComp)).all()
    assert len(rows) == 1
    comp = rows[0]
    # Plausible exponents (session 34: the fixture used to give 131.8 kg fat and 327 kg muscle on a 72.4 kg person). Muscle + bone +
    # fat mass ≈ weight, as in the live readings checked on 2026-11-22.
    assert comp.weight_kg == 72.4
    assert comp.fat_pct == 18.2
    assert comp.fat_kg == 13.18
    assert comp.muscle_kg == 56.5
    assert comp.hydration_kg == 42.1
    assert comp.bone_kg == 2.72
    assert abs(comp.muscle_kg + comp.bone_kg + comp.fat_kg - comp.weight_kg) < 0.1


def test_status_nonzero_raises(monkeypatch, session):
    monkeypatch.setattr(withings_client, "settings", FAKE_SETTINGS)

    def fake_post(url, data=None, headers=None, timeout=None):
        return _resp(url, status_code=200, json={"status": 503, "body": {}})

    monkeypatch.setattr(withings_client.httpx, "post", fake_post)

    import pytest

    with pytest.raises(withings_client.WithingsError):
        withings_client._get_nonce()
