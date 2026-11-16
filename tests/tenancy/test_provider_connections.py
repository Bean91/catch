"""Session 25 on the public deployment: two users, one provider, no crossover; no server-wide fallback; the signed OAuth callback;
a tick that keeps going when one user's provider fails."""

from __future__ import annotations

import base64
import dataclasses
import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlmodel import Session

from catch.core import secret_store, tenant
from catch.core.config import settings as real_settings
from catch.core.models import ProviderConnection, SyncState
from catch.sync import connections, scheduler
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A, B = bearer(kit.ALICE), bearer(kit.BOB)
TICK = {"authorization": "Bearer tick-secret-for-tests"}


def _jwt() -> str:
    def b64(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")

    now = int(datetime.now(timezone.utc).timestamp())
    return f"{b64({'alg': 'RS256'})}.{b64({'exp': now + 86400, 'iat': now, 'garmin_guid': 'g'})}.s"


@pytest.fixture()
def garmin_accepts(monkeypatch):
    seen = []

    def post(url, headers=None, timeout=None):
        seen.append(headers["Authorization"])
        return httpx.Response(200, text=_jwt(), request=httpx.Request("POST", url))

    monkeypatch.setattr("catch.sync.garmin_client.httpx.post", post)
    return seen


@pytest.fixture()
def profiles(pub_client):
    for h in (A, B):
        assert pub_client.get("/api/me", headers=h).status_code == 200


def _rows(pub_engine):
    with Session(pub_engine) as s:
        return s.execute(select(ProviderConnection).execution_options(tenant_unscoped=True)).scalars().all()


def test_two_users_connect_the_same_provider_without_any_crossover(pub_client, pub_engine, profiles, garmin_accepts):
    key_a, key_b = "alice-garmin-personal-key-AAAA1111", "bob-garmin-personal-key-BBBB2222"
    assert pub_client.put("/api/connections/garmin/credential", headers=A, json={"api_key": key_a}).status_code == 200
    assert pub_client.put("/api/connections/garmin/credential", headers=B, json={"api_key": key_b}).status_code == 200
    assert garmin_accepts == [f"ApiKey {key_a}", f"ApiKey {key_b}"]

    cards = {name: {c["provider"]: c for c in pub_client.get("/api/connections", headers=h).json()["connections"]} for name, h in (("a", A), ("b", B))}
    assert cards["a"]["garmin"]["last4"] == "1111" and cards["b"]["garmin"]["last4"] == "2222"
    for text in (json.dumps(cards["a"]), json.dumps(cards["b"])):
        assert "personal-key" not in text

    rows = {r.owner_id: r for r in _rows(pub_engine)}
    assert set(rows) == {kit.ALICE, kit.BOB} and rows[kit.ALICE].credential_enc != rows[kit.BOB].credential_enc
    with pytest.raises(secret_store.SecretStoreError):  # Bob's row sealed for Bob; Alice's blob can't be opened as Bob's
        secret_store.open_sealed(rows[kit.ALICE].credential_enc, owner_id=kit.BOB, provider="garmin:credential", purpose=secret_store.CONNECTION_PURPOSE)
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        assert connections.credential(s, "garmin") == key_a
    with tenant.use_owner(kit.BOB), Session(pub_engine) as s:
        assert connections.credential(s, "garmin") == key_b

    # Alice disconnecting leaves Bob connected
    assert pub_client.delete("/api/connections/garmin", headers=A).json()["was_connected"] is True
    assert pub_client.get("/api/connections", headers=A).json()["connections"][0]["connected"] is False
    assert pub_client.get("/api/connections", headers=B).json()["connections"][0]["connected"] is True


def test_the_public_deployment_never_falls_back_to_a_server_wide_credential(pub_client, pub_engine, profiles, monkeypatch):
    monkeypatch.setattr(connections, "settings", dataclasses.replace(real_settings, garmin_api_key="OPERATORS-OWN-GARMIN-KEY", concept2_access_token="OPERATORS-OWN-C2-TOKEN"))
    cards = {c["provider"]: c for c in pub_client.get("/api/connections", headers=A).json()["connections"]}
    assert cards["garmin"]["connected"] is False and cards["concept2"]["connected"] is False
    for source in ("garmin", "concept2"):
        assert pub_client.post(f"/api/sync/{source}", headers=A).json() == {"source": source, "skipped": "not connected"}
    assert _rows(pub_engine) == []


def test_the_operator_can_switch_off_garmin_byok(pub_client, profiles, garmin_accepts, monkeypatch):
    monkeypatch.setattr("catch.sync.providers.settings", dataclasses.replace(real_settings, garmin_byok_enabled=False))
    r = pub_client.put("/api/connections/garmin/credential", headers=A, json={"api_key": "some-personal-key-0123456"})
    assert r.status_code == 404 and garmin_accepts == []
    assert pub_client.get("/api/connections", headers=A).json()["connections"][0]["available"] is False


def test_connection_routes_need_a_signed_in_user(pub_client):
    assert pub_client.get("/api/connections").status_code == 401
    assert pub_client.put("/api/connections/garmin/credential", json={"api_key": "x" * 20}).status_code == 401
    assert pub_client.post("/api/connections/whoop/oauth/start").status_code == 401


@pytest.fixture()
def whoop_configured(monkeypatch):
    from catch.sync import whoop_client as wc

    monkeypatch.setattr(wc, "settings", dataclasses.replace(wc.settings, whoop_client_id="cid", whoop_client_secret="cs", whoop_redirect_uri="https://catch.test/auth/whoop/callback"))


def test_oauth_callback_attaches_the_code_to_the_user_who_started_it_and_only_that_user(pub_client, pub_engine, profiles, whoop_configured, monkeypatch):
    from catch.sync import whoop_client as wc

    exchanged = []

    def fake_exchange(session, code, transport=None):
        exchanged.append((tenant.current_owner(), code))
        connections.store_oauth(session, "whoop", access="WA" * 12, refresh="WR" * 12, expires_in=3600)

    monkeypatch.setattr(wc, "exchange_code", fake_exchange)
    start = pub_client.post("/api/connections/whoop/oauth/start", headers=A)
    assert start.status_code == 200
    url = httpx.URL(start.json()["authorize_url"])
    state = url.params["state"]
    assert len(state) == 8 and "catch_oauth_whoop" in start.headers["set-cookie"] and "HttpOnly" in start.headers["set-cookie"]

    # the callback is hit by the browser with NO bearer token: identity comes from the signed cookie alone
    pub_client.cookies.set("catch_oauth_whoop", start.cookies["catch_oauth_whoop"])
    done = pub_client.get("/auth/whoop/callback", params={"code": "the-code", "state": state}, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"] == "/settings/connections?provider=whoop&result=connected"
    assert exchanged == [(kit.ALICE, "the-code")]
    assert [r.owner_id for r in _rows(pub_engine)] == [kit.ALICE]
    assert {c["provider"]: c["connected"] for c in pub_client.get("/api/connections", headers=B).json()["connections"]}["whoop"] is False
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        assert s.get(SyncState, tenant.pk("whoop")).backfill_cursor  # history queued, not imported inside the callback

    # a link forged for Bob with Alice's cookie, or a wrong state, does nothing
    bad = pub_client.get("/auth/whoop/callback", params={"code": "x", "state": "WRONGSTA"}, follow_redirects=False)
    assert bad.status_code == 400 and len(exchanged) == 1


def test_a_callback_for_an_account_deleted_in_the_meantime_fails_cleanly(pub_client, pub_engine, profiles, whoop_configured, monkeypatch):
    from catch.core import oauth_state
    from catch.sync import whoop_client as wc

    monkeypatch.setattr(wc, "exchange_code", lambda *a, **k: pytest.fail("must not exchange for a deleted account"))
    nonce = oauth_state.new_nonce("whoop")
    pub_client.cookies.set("catch_oauth_whoop", oauth_state.make("ghost-user", "whoop", nonce))
    done = pub_client.get("/auth/whoop/callback", params={"code": "c", "state": nonce}, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"].endswith("result=failed")


def test_one_users_failing_provider_never_stops_another_users_sync(pub_client, pub_engine, profiles, monkeypatch):
    for owner, key in ((kit.ALICE, "alice-c2-token-123456"), (kit.BOB, "bob-c2-token-1234567")):
        with tenant.use_owner(owner), Session(pub_engine) as s:
            connections.store_credential(s, "concept2", key, auth_method="personal_token")
    ran = []

    def fake_provider(session, source, days):
        owner = tenant.current_owner()
        ran.append((owner, source))
        if owner == kit.ALICE:
            raise RuntimeError("alice's provider is down")
        return {"results": 1}

    monkeypatch.setattr(scheduler, "_sync_provider", fake_provider)
    monkeypatch.setattr(scheduler, "_advance_backfill", lambda session, source: None)
    out = pub_client.post("/internal/tick/sync", headers=TICK).json()
    assert out["users"] == 2 and out["failed"] == 0
    assert (kit.BOB, "concept2") in ran and (kit.ALICE, "concept2") in ran
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        assert s.get(SyncState, tenant.pk("concept2")).consecutive_failures == 1
        assert connections.get(s, "concept2").status == connections.ERROR
    with tenant.use_owner(kit.BOB), Session(pub_engine) as s:
        row = s.get(SyncState, tenant.pk("concept2"))
        assert row.last_success_at is not None and row.consecutive_failures == 0
        assert connections.get(s, "concept2").status == connections.CONNECTED


def test_a_sync_already_running_for_this_user_and_provider_is_not_started_twice(pub_engine, profiles, monkeypatch):
    from catch.sync import lease

    with tenant.use_owner(kit.ALICE):
        with Session(pub_engine) as s:
            connections.store_credential(s, "concept2", "alice-c2-token-123456", auth_method="personal_token")
            assert lease.claim(s, "sync:concept2") is True  # another replica holds it
        monkeypatch.setattr(scheduler, "_sync_provider", lambda *a: pytest.fail("a second run must not start"))
        assert scheduler.run_sync("concept2", manual=True) == {"source": "concept2", "skipped": "already running"}
    with tenant.use_owner(kit.BOB), Session(pub_engine) as s:  # the same provider for another user is unaffected
        connections.store_credential(s, "concept2", "bob-c2-token-1234567", auth_method="personal_token")
    monkeypatch.setattr(scheduler, "_sync_provider", lambda *a: {"results": 0})
    monkeypatch.setattr(scheduler, "_advance_backfill", lambda *a: None)
    with tenant.use_owner(kit.BOB):
        assert scheduler.run_sync("concept2", manual=True)["source"] == "concept2"


def test_the_lease_is_released_even_when_the_sync_fails(pub_engine, profiles, monkeypatch):
    with tenant.use_owner(kit.ALICE):
        with Session(pub_engine) as s:
            connections.store_credential(s, "concept2", "alice-c2-token-123456", auth_method="personal_token")
        monkeypatch.setattr(scheduler, "_sync_provider", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
        assert "error" in scheduler.run_sync("concept2", manual=True)
        monkeypatch.setattr(scheduler, "_sync_provider", lambda *a: {"results": 0})
        monkeypatch.setattr(scheduler, "_advance_backfill", lambda *a: None)
        assert scheduler.run_sync("concept2", manual=True)["source"] == "concept2"  # not "already running"


def test_deleting_an_account_revokes_whoop_before_the_rows_go(pub_client, pub_engine, profiles, monkeypatch):
    from catch.sync import whoop_client as wc

    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        connections.store_oauth(s, "whoop", access="WA" * 12, refresh="WR" * 12, expires_in=3600)
    revoked = []
    monkeypatch.setattr(wc.WhoopApi, "revoke", lambda self: revoked.append(tenant.current_owner()) or True)
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        connections.revoke_all_for_account_deletion(s)
    assert revoked == [kit.ALICE] and _rows(pub_engine) == []
