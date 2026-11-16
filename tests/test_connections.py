"""Per-user provider connections (session 25): sealing, the BYOK/credential flows, adoption of legacy rows, backoff, paced history
import, the lease and the signed OAuth state. Fixtures only — no live provider is ever called."""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import json
import logging
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlmodel import select

from catch.core import oauth_state, secret_store, security, tenant
from catch.core.config import settings as real_settings
from catch.core.models import Activity, OAuthToken, ProviderConnection, SyncState
from catch.sync import concept2_client, connections, lease, scheduler, state
from catch.sync import garmin_client
from tests.conftest import TEST_PASSWORD

from catch.core.principal import ATHLETE  # noqa: E402

ATHLETE_CTX = {"principal": ATHLETE}
KEY = "garmin-personal-api-key-SECRET-0123456789"
SECRET_FRAGMENT = "SECRET-0123456789"


def _jwt(claims: dict | None = None) -> str:
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    now = int(datetime.now(timezone.utc).timestamp())
    return f"{b64({'alg': 'RS256'})}.{b64({'exp': now + 86400, 'iat': now, 'garmin_guid': 'guid-1', 'scope': 'PERSONAL_API_WELLNESS_READ', **(claims or {})})}.sig"


@pytest.fixture()
def garmin_http(monkeypatch):
    calls = {"n": 0, "keys": []}

    def fake_post(url, headers=None, timeout=None):
        calls["n"] += 1
        calls["keys"].append(headers["Authorization"])
        if headers["Authorization"] == f"ApiKey {KEY}" or headers["Authorization"].endswith("-good"):
            return httpx.Response(200, text=_jwt(), request=httpx.Request("POST", url))
        return httpx.Response(401, text="no", request=httpx.Request("POST", url))

    monkeypatch.setattr("catch.sync.garmin_client.httpx.post", fake_post)
    return calls


@pytest.fixture()
def fake_session_ctx(session, monkeypatch):
    @contextlib.contextmanager
    def ctx():
        yield session

    monkeypatch.setattr(scheduler, "get_session", ctx)
    return session


def _login(client):
    assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 200


# -- sealing --------------------------------------------------------------------------------------------------------------


def test_credentials_are_sealed_per_owner_provider_and_slot(session):
    connections.store_credential(session, "garmin", KEY, auth_method="api_key")
    row = session.get(ProviderConnection, tenant.pk("garmin"))
    assert SECRET_FRAGMENT not in (row.credential_enc or "") and row.credential_enc.startswith("v1.")
    assert connections.credential(session, "garmin") == KEY
    # moved to another slot / provider / owner it fails closed rather than yielding the secret
    for owner, scope in (("someone-else", "garmin:credential"), ("owner", "garmin:access"), ("owner", "whoop:credential")):
        with pytest.raises(secret_store.SecretStoreError):
            secret_store.open_sealed(row.credential_enc, owner_id=owner, provider=scope, purpose=secret_store.CONNECTION_PURPOSE)
    # and the AI-key key domain can't open it either
    with pytest.raises(secret_store.SecretStoreError):
        secret_store.open_sealed(row.credential_enc, owner_id="owner", provider="garmin:credential")


def test_a_credential_sealed_under_the_previous_master_key_still_opens(session, monkeypatch):
    connections.store_oauth(session, "whoop", access="A" * 24, refresh="R" * 24, expires_in=3600)
    rotated = dataclasses.replace(real_settings, secrets_master_key="a-brand-new-master-key-0123456789abcdef", secrets_master_key_previous=real_settings.secrets_master_key)
    monkeypatch.setattr(secret_store, "settings", rotated)
    assert connections.oauth_tokens(session, "whoop").refresh == "R" * 24
    assert secret_store.needs_reseal(session.get(ProviderConnection, tenant.pk("whoop")).key_id)


def test_the_card_never_carries_a_secret(session):
    connections.store_credential(session, "garmin", KEY, auth_method="api_key", expires_on=date(2027, 1, 1))
    connections.store_oauth(session, "whoop", access="ACCESS-TOKEN-XYZ-123456", refresh="REFRESH-TOKEN-XYZ-123456", expires_in=3600)
    blob = json.dumps(connections.list_cards(session) + connections.sync_summary(session))
    for secret in (KEY, SECRET_FRAGMENT, "ACCESS-TOKEN-XYZ", "REFRESH-TOKEN-XYZ"):
        assert secret not in blob
    garmin = connections.card(session, "garmin")
    assert garmin["last4"] == KEY[-4:] and garmin["credential_expires_on"] == "2027-01-01" and garmin["auth_method"] == "api_key"
    assert "access_enc" not in garmin and "credential_enc" not in garmin


# -- Garmin BYOK through the REST routes ------------------------------------------------------------------------------------


def test_garmin_connect_replace_and_a_rejected_key_that_must_not_destroy_the_working_one(client, session, garmin_http, caplog):
    _login(client)
    caplog.set_level(logging.DEBUG)
    ok = client.put("/api/connections/garmin/credential", json={"api_key": KEY, "expires_on": "2027-03-01"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["connected"] and body["status"] == "connected" and body["last4"] == KEY[-4:] and body["credential_expires_on"] == "2027-03-01"
    assert body["scopes"] == ["PERSONAL_API_WELLNESS_READ"] and body["importing_history_from"]  # history import queued, not run inline
    assert KEY not in ok.text

    bad = client.put("/api/connections/garmin/credential", json={"api_key": "typo-typo-typo-typo"})
    assert bad.status_code == 422 and "Personal API key" in bad.json()["detail"] and "typo-typo" not in bad.text
    assert connections.credential(session, "garmin") == KEY  # still the working key

    new_key = "a-newer-personal-key-good"
    assert client.put("/api/connections/garmin/credential", json={"api_key": new_key}).status_code == 200
    assert connections.credential(session, "garmin") == new_key
    assert connections.cached_access(session, "garmin").access  # the cached JWT belongs to the new key

    listing = client.get("/api/connections")
    assert listing.status_code == 200 and KEY not in listing.text and new_key not in listing.text
    assert KEY not in caplog.text and new_key not in caplog.text and "ApiKey" not in caplog.text


def test_garmin_needs_no_developer_program_credentials_and_the_key_is_the_only_input(client, session, garmin_http):
    assert not hasattr(garmin_client, "settings")  # the client has no path to any server-wide Garmin setting
    _login(client)
    assert client.put("/api/connections/garmin/credential", json={"api_key": KEY}).status_code == 200
    assert garmin_http["keys"] == [f"ApiKey {KEY}"]  # the one exchange used exactly the user's key


def test_an_unreachable_provider_saves_nothing(client, session, monkeypatch):
    _login(client)

    def down(url, headers=None, timeout=None):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr("catch.sync.garmin_client.httpx.post", down)
    r = client.put("/api/connections/garmin/credential", json={"api_key": KEY})
    assert r.status_code == 422 and "Nothing was saved" in r.json()["detail"]
    assert connections.get(session, "garmin") is None


def test_concept2_personal_token_is_validated_then_sealed(client, session, monkeypatch):
    _login(client)
    monkeypatch.setattr(concept2_client, "validate_token", lambda token, transport=None: {"account_id": "42"} if token == "good-c2-token-123456" else (_ for _ in ()).throw(concept2_client.Concept2AuthError("no")))
    assert client.put("/api/connections/concept2/credential", json={"api_key": "bad-c2-token-0000000"}).status_code == 422
    ok = client.put("/api/connections/concept2/credential", json={"api_key": "good-c2-token-123456"}).json()
    assert ok["auth_method"] == "personal_token" and ok["connected"] and "good-c2-token" not in json.dumps(ok)
    assert connections.credential(session, "concept2") == "good-c2-token-123456"


def test_oauth_providers_refuse_a_pasted_key_and_garmin_has_no_oauth(client):
    _login(client)
    assert client.put("/api/connections/whoop/credential", json={"api_key": "x" * 20}).status_code == 422
    assert client.post("/api/connections/garmin/oauth/start").status_code == 422
    assert client.get("/api/connections/garmin").status_code in (404, 405)


def test_connection_routes_are_not_reachable_with_a_device_token(client, session):
    from catch.api.deps import hash_token
    from catch.core.models import ApiToken

    session.add(ApiToken(name="d", token_hash=hash_token("device-token-abc")))
    session.commit()
    assert client.get("/api/connections", headers={"Authorization": "Bearer device-token-abc"}).status_code == 401
    assert client.put("/api/connections/garmin/credential", json={"api_key": KEY}, headers={"Authorization": "Bearer device-token-abc"}).status_code == 401


# -- disconnect / reconnect, history stays -----------------------------------------------------------------------------------


def test_disconnect_forgets_credentials_keeps_history_and_reconnecting_works(client, session, garmin_http):
    _login(client)
    client.put("/api/connections/garmin/credential", json={"api_key": KEY})
    session.add(Activity(source="garmin", external_id="1", type="rowing", start=datetime(2026, 11, 1, tzinfo=timezone.utc), duration=600))
    session.commit()
    out = client.delete("/api/connections/garmin").json()
    assert out["was_connected"] is True
    assert session.get(ProviderConnection, tenant.pk("garmin")) is None and session.get(SyncState, tenant.pk("garmin")) is None
    assert len(session.exec(select(Activity)).all()) == 1  # the imported record stays
    assert client.get("/api/connections").json()["connections"][0]["connected"] is False
    assert client.put("/api/connections/garmin/credential", json={"api_key": KEY}).status_code == 200
    assert connections.credential(session, "garmin") == KEY


def test_whoop_disconnect_revokes_at_whoop_then_deletes_tokens(session):
    from catch.sync import whoop_client as wc

    connections.store_oauth(session, "whoop", access="WA" * 12, refresh="WR" * 12, expires_in=3600)
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(204)

    out = wc.disconnect(session, httpx.MockTransport(handler))
    assert out == {"revoked": True, "was_connected": True} and seen == [("DELETE", "/developer/v2/user/access")]
    assert connections.get(session, "whoop") is None


# -- legacy rows (the Pi) ----------------------------------------------------------------------------------------------------


def test_a_legacy_oauth_row_is_adopted_once_and_removed_in_the_same_step(session):
    session.add(OAuthToken(source="withings", access_token_enc=security.encrypt("old-access"), refresh_token_enc=security.encrypt("old-refresh"), expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    session.commit()
    row = connections.get(session, "withings")
    assert row is not None and row.auth_method == "oauth"
    assert session.get(OAuthToken, tenant.pk("withings")) is None  # a rotating refresh token must live in exactly one place
    t = connections.oauth_tokens(session, "withings")
    assert (t.access, t.refresh) == ("old-access", "old-refresh")


def test_the_personal_install_keeps_using_an_environment_key_and_credential_reads_it_live(session, monkeypatch):
    monkeypatch.setattr(connections, "settings", dataclasses.replace(real_settings, garmin_api_key="env-garmin-key-123456", concept2_access_token="env-c2-token-123456"))
    row = connections.get(session, "garmin")
    assert row.status_detail == "from_environment" and row.credential_enc is None
    assert connections.credential(session, "garmin") == "env-garmin-key-123456"
    monkeypatch.setattr(connections, "settings", dataclasses.replace(real_settings, garmin_api_key="rotated-env-key-654321"))
    assert connections.credential(session, "garmin") == "rotated-env-key-654321"  # rotating .env needs no re-save
    monkeypatch.setattr(connections, "settings", dataclasses.replace(real_settings, concept2_access_token="env-c2-token-123456"))
    assert connections.get(session, "concept2").status_detail == "from_environment"
    assert connections.credential(session, "concept2") == "env-c2-token-123456"


# -- sync engine: status, backoff, lease, paced history -------------------------------------------------------------------


def test_rate_limiting_defers_the_next_attempt_and_is_not_a_failure_of_the_connection(fake_session_ctx, monkeypatch):
    from catch.sync.providers.base import ProviderRateLimited

    session = fake_session_ctx
    connections.store_credential(session, "concept2", "token-for-c2-123456", auth_method="personal_token")

    def limited(*a, **k):
        raise ProviderRateLimited(retry_after=3600)

    monkeypatch.setattr(concept2_client, "sync", limited)
    out = scheduler.run_sync("concept2")
    assert out["rate_limited"] is True
    row = session.get(SyncState, tenant.pk("concept2"))
    assert row.next_attempt_at - datetime.now(timezone.utc).replace(tzinfo=row.next_attempt_at.tzinfo) > timedelta(minutes=50)
    assert connections.get(session, "concept2").status == connections.RATE_LIMITED
    assert scheduler.run_sync("concept2")["skipped"] == "backing off"


def test_backoff_doubles_and_is_capped():
    assert [state.backoff_seconds(n) for n in (1, 2, 3)] == [300, 600, 1200]
    assert state.backoff_seconds(20) == state.BACKOFF_CAP_S
    assert state.backoff_seconds(1, retry_after=999999) == state.BACKOFF_CAP_S


def test_a_successful_sync_restores_a_connection_marked_for_reconnect(fake_session_ctx, monkeypatch):
    session = fake_session_ctx
    connections.store_credential(session, "concept2", "token-for-c2-123456", auth_method="personal_token")
    connections.mark(session, "concept2", connections.NEEDS_RECONNECT, "key_rejected")
    monkeypatch.setattr(concept2_client, "sync", lambda *a, **k: {"results": 0})
    assert scheduler.run_sync("concept2")["skipped"] == "needs reconnect"
    assert scheduler.run_sync("concept2", manual=True)["source"] == "concept2"
    assert connections.get(session, "concept2").status == connections.CONNECTED


def test_a_new_credential_clears_needs_reconnect(session):
    connections.store_credential(session, "concept2", "token-for-c2-123456", auth_method="personal_token")
    connections.mark(session, "concept2", connections.NEEDS_RECONNECT, "key_rejected")
    connections.store_credential(session, "concept2", "another-token-7654321", auth_method="personal_token")
    assert connections.get(session, "concept2").status == connections.CONNECTED


def test_history_is_imported_one_window_per_run_and_a_failed_window_is_retried(fake_session_ctx, monkeypatch):
    session = fake_session_ctx
    connections.store_credential(session, "concept2", "token-for-c2-123456", auth_method="personal_token")
    scheduler.start_backfill(session, "concept2", days=70)
    first = session.get(SyncState, tenant.pk("concept2")).backfill_cursor
    assert first == (date.today() - timedelta(days=70)).isoformat()
    assert connections.get(session, "concept2").status_detail == "backfilling"

    windows, fail = [], {"on": True}

    def fake_window(session_, source, start, end):
        if fail["on"]:
            fail["on"] = False
            raise RuntimeError("boom")
        windows.append((start, end))
        return {"results": 1}

    monkeypatch.setattr(scheduler, "_sync_window", fake_window)
    monkeypatch.setattr(concept2_client, "sync", lambda *a, **k: {"results": 0})
    out = scheduler.run_sync("concept2", manual=True)
    assert out["backfill"]["deferred"] == "window_failed" and session.get(SyncState, tenant.pk("concept2")).backfill_cursor == first
    for _ in range(4):
        scheduler.run_sync("concept2", manual=True)
    assert windows[0][0] == date.fromisoformat(first) and (windows[0][1] - windows[0][0]).days == scheduler.BACKFILL_WINDOW_DAYS - 1
    assert all(b[0] == a[1] + timedelta(days=1) for a, b in zip(windows, windows[1:]))  # contiguous, no gap, no overlap
    assert session.get(SyncState, tenant.pk("concept2")).backfill_cursor is None
    assert windows[-1][1] == date.today()
    assert connections.get(session, "concept2").status_detail is None


def test_the_sync_lease_blocks_a_second_claim_until_released_or_stale(session):
    assert lease.claim(session, "sync:whoop") is True
    assert lease.claim(session, "sync:whoop") is False
    lease.finish(session, "sync:whoop")
    assert lease.claim(session, "sync:whoop") is True
    row = session.get(SyncState, tenant.pk("job:sync:whoop"))
    row.last_attempt_at = datetime.now(timezone.utc) - lease.LEASE - timedelta(seconds=1)
    session.commit()
    assert lease.claim(session, "sync:whoop") is True  # a crashed run's lease expires on its own


def test_run_sync_skips_unconnected_sources_without_recording_anything(fake_session_ctx):
    for source in scheduler.SOURCES:
        assert scheduler.run_sync(source) == {"source": source, "skipped": "not connected"}
    assert fake_session_ctx.exec(select(SyncState)).all() == []


# -- signed OAuth state ------------------------------------------------------------------------------------------------------


def test_oauth_state_binds_owner_provider_nonce_and_expiry():
    nonce = oauth_state.new_nonce("whoop")
    assert len(nonce) == 8 and len(oauth_state.new_nonce("withings")) > 8
    cookie = oauth_state.make("alice", "whoop", nonce, now=1000.0)
    assert oauth_state.verify(cookie, "whoop", nonce, now=1100.0) == "alice"
    body, sig = cookie.rsplit(".", 1)
    forged = base64.urlsafe_b64encode(json.dumps({"o": "bob", "p": "whoop", "n": nonce, "e": 99999999999}).encode()).decode().rstrip("=")
    for bad_cookie, provider, st, now in (
        (f"{forged}.{sig}", "whoop", nonce, 1100.0),  # edited payload
        (cookie, "withings", nonce, 1100.0),  # another provider's callback
        (cookie, "whoop", "WRONGSTA", 1100.0),  # state doesn't match the cookie's nonce
        (cookie, "whoop", nonce, 1000.0 + oauth_state.TTL_SECONDS + 1),  # expired
        (None, "whoop", nonce, 1100.0),
        ("garbage", "whoop", nonce, 1100.0),
    ):
        with pytest.raises(oauth_state.OAuthStateError):
            oauth_state.verify(bad_cookie, provider, st, now=now)


def test_the_callback_needs_the_signed_cookie_and_rejects_forgeries(client, monkeypatch):
    from catch.sync import whoop_client as wc

    monkeypatch.setattr(wc, "settings", dataclasses.replace(wc.settings, whoop_client_id="cid", whoop_client_secret="cs", whoop_redirect_uri="http://localhost:8000/auth/whoop/callback"))
    assert client.get("/auth/whoop/callback", params={"code": "c", "state": "abcdefgh"}).status_code == 400  # no cookie at all
    client.cookies.set("catch_oauth_whoop", "forged.cookie")
    assert client.get("/auth/whoop/callback", params={"code": "c", "state": "abcdefgh"}).status_code == 400


def test_the_authorization_code_is_never_logged_or_returned(client, monkeypatch, caplog):
    from catch.sync import whoop_client as wc

    monkeypatch.setattr(wc, "settings", dataclasses.replace(wc.settings, whoop_client_id="cid", whoop_client_secret="cs", whoop_redirect_uri="http://localhost:8000/auth/whoop/callback"))
    _login(client)
    caplog.set_level(logging.DEBUG)

    def boom(session, code, transport=None):
        raise RuntimeError("provider said no")

    monkeypatch.setattr(wc, "exchange_code", boom)
    start = client.post("/api/connections/whoop/oauth/start").json()
    state_ = httpx.URL(start["authorize_url"]).params["state"]
    out = client.get("/auth/whoop/callback", params={"code": "AUTH-CODE-SHOULD-NOT-LEAK", "state": state_}, follow_redirects=False)
    assert out.headers["location"].endswith("result=failed") and "AUTH-CODE" not in out.text + str(out.headers) + caplog.text


# -- coach / MCP tools -----------------------------------------------------------------------------------------------------


def test_connection_tools_report_state_and_preview_before_syncing(session, monkeypatch):
    from catch.coach import tools

    connections.store_credential(session, "garmin", KEY, auth_method="api_key")
    connections.store_oauth(session, "whoop", access="ACCESS-TOKEN-XYZ-123456", refresh="REFRESH-TOKEN-XYZ-123456", expires_in=3600)
    got = tools.call_tool(session, "get_connected_providers", {}, ctx=ATHLETE_CTX)
    dumped = json.dumps(got) + json.dumps(tools.call_tool(session, "get_sync_status", {}, ctx=ATHLETE_CTX))
    for secret in (KEY, SECRET_FRAGMENT, "ACCESS-TOKEN-XYZ", "REFRESH-TOKEN-XYZ"):
        assert secret not in dumped
    by = {p["provider"]: p for p in got["providers"]}
    assert by["garmin"]["connected"] and by["whoop"]["connected"] and not by["withings"]["connected"]
    assert "last4" not in by["garmin"] and "token_expires_at" not in by["whoop"]

    ran = []
    monkeypatch.setattr(scheduler, "run_sync", lambda source, days=3, manual=False: ran.append((source, manual)) or {"source": source})
    preview = tools.call_tool(session, "sync_provider", {"provider": "whoop"}, ctx=ATHLETE_CTX)
    assert preview["saved"] is False and "preview" in preview and ran == []
    done = tools.call_tool(session, "sync_provider", {"provider": "whoop", "confirm": True}, ctx=ATHLETE_CTX)
    assert done["saved"] is True and ran == [("whoop", True)]
    with pytest.raises(ValueError, match="isn't connected"):
        tools.call_tool(session, "sync_provider", {"provider": "withings", "confirm": True}, ctx=ATHLETE_CTX)


def test_the_connection_tools_refuse_an_unidentified_or_coach_caller(session):
    from catch.coach import tools
    from catch.core.principal import VIEWER

    for ctx in ({}, {"principal": VIEWER}):
        for name, args in (("get_connected_providers", {}), ("get_sync_status", {}), ("sync_provider", {"provider": "whoop", "confirm": True})):
            with pytest.raises(ValueError):
                tools.call_tool(session, name, args, ctx=ctx)


def test_connection_tools_are_athlete_only_and_have_no_credential_arguments():
    from catch.coach import tools
    from catch.core.principal import COACH_TOOLS

    for name in ("get_connected_providers", "get_sync_status", "sync_provider"):
        assert name not in COACH_TOOLS
        props = tools.TOOLS[name]["input_schema"]["properties"]
        assert not set(props) - {"provider", "confirm"}
    assert tools.TOOLS["sync_provider"]["write"] is True


# -- a credential kept in .env can't be "disconnected" from the UI (it would be re-adopted straight away) --------------------------


def test_disconnecting_an_environment_credential_is_refused_with_a_plain_reason(client, session, monkeypatch):
    _login(client)
    monkeypatch.setattr(connections, "settings", dataclasses.replace(real_settings, garmin_api_key="env-garmin-key-123456"))
    assert client.get("/api/connections").json()["connections"][0]["from_environment"] is True
    r = client.delete("/api/connections/garmin")
    assert r.status_code == 409 and ".env" in r.json()["detail"]
    card = client.get("/api/connections").json()["connections"][0]
    assert card["connected"] is True and "env-garmin-key" not in json.dumps(card)

    # a key pasted in the UI replaces it for this account, after which it is a normal, removable connection
    connections.store_credential(session, "garmin", "pasted-in-the-ui-key-123456", auth_method="api_key")
    assert client.get("/api/connections").json()["connections"][0]["from_environment"] is False
    assert client.delete("/api/connections/garmin").status_code == 200


def test_a_withings_data_call_status_other_than_401_or_601_is_a_plain_error_not_a_reconnect():
    from catch.sync import withings_client
    from catch.sync.providers.base import ProviderAuthError, ProviderRateLimited

    for status in (100, 101, 102, 293, 503):
        with pytest.raises(withings_client.WithingsError) as exc:
            withings_client._check_status({"status": status}, "getmeas")
        assert not isinstance(exc.value, ProviderAuthError)
    with pytest.raises(ProviderAuthError):
        withings_client._check_status({"status": 401}, "getmeas")
    with pytest.raises(ProviderRateLimited):
        withings_client._check_status({"status": 601}, "getmeas")
