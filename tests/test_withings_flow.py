"""Session 34: the whole Withings connection, end to end through the real routes and sync engine, against tests/withings_fake.py (which
enforces the signature, single-use nonces and codes, the registered callback URL and rotating refresh tokens Withings enforces). Personal
deployment; the public two-user version is tests/tenancy/test_withings_isolation.py."""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time

import httpx
import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

from catch.core import tenant
from catch.core.models import BodyComp, ProviderConnection, SyncState
from catch.sync import connections, scheduler, withings_client
from tests import withings_fake as wf
from tests.conftest import TEST_PASSWORD

USER = 4242
NOW = int(time.time())


@pytest.fixture()
def fake(monkeypatch):
    f = wf.FakeWithings()
    wf.configure(monkeypatch, f)
    f.groups[USER] = [wf.group(1001, NOW - 60 * 3600, 64.4, fat_kg=6.3), wf.group(1002, NOW - 36 * 3600, 64.1), wf.group(1003, NOW - 12 * 3600, 63.9)]
    return f


@pytest.fixture()
def sync_session(session, monkeypatch):
    @contextlib.contextmanager
    def ctx():
        yield session

    monkeypatch.setattr(scheduler, "get_session", ctx)
    monkeypatch.setattr("catch.sync.scoring.recompute_scores", lambda *a, **k: None)
    return session


def _login(client):
    assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 200


def _connect(client, fake, *, userid=USER, code=None):
    start = client.post("/api/connections/withings/oauth/start")
    assert start.status_code == 200
    url = httpx.URL(start.json()["authorize_url"])
    assert url.host == "account.withings.com" and url.params["scope"] == "user.metrics" and url.params["redirect_uri"] == wf.REDIRECT_URI
    code = code or fake.issue_code(userid)
    return client.get("/auth/withings/callback", params={"code": code, "state": url.params["state"]}, follow_redirects=False), url.params["state"], code


def _card(client):
    return next(c for c in client.get("/api/connections").json()["connections"] if c["provider"] == "withings")


def test_connect_sync_resync_disconnect_reconnect(client, session, fake, sync_session, caplog):
    caplog.set_level(logging.DEBUG)
    _login(client)
    done, _, code = _connect(client, fake)
    assert done.status_code == 303 and done.headers["location"] == "/settings/connections?provider=withings&result=connected"
    assert fake.token_requests[0]["grant_type"] == "authorization_code" and fake.token_requests[0]["redirect_uri"] == wf.REDIRECT_URI

    card = _card(client)
    assert card["connected"] and card["status"] == "connected" and card["account_connected_at"] and card["scopes"] == ["user.metrics"]
    row = session.get(ProviderConnection, tenant.pk("withings"))
    assert row.account_id == str(USER)
    tokens = connections.oauth_tokens(session, "withings")
    assert tokens.access.startswith("withings-access-") and tokens.access not in (row.access_enc or "")  # sealed at rest
    assert session.get(SyncState, tenant.pk("withings")).backfill_cursor  # history queued, not imported inside the callback

    first = scheduler.run_sync("withings", manual=True)
    assert first["measures"] == 3 and "startdate" in fake.measure_calls[0]  # no cursor yet: a bounded window, never everything
    calls_before = len(fake.measure_calls)
    scheduler.run_sync("withings", manual=True)
    cursor = int(session.get(SyncState, tenant.pk("withings")).cursor)
    assert "lastupdate" in fake.measure_calls[calls_before]  # incremental from the stored cursor
    assert cursor <= int(time.time())
    rows = session.exec(select(BodyComp).where(BodyComp.source == "withings")).all()
    assert sorted(r.external_id for r in rows) == ["1001", "1002", "1003"]  # upserted on grpid — no duplicates
    assert {r.external_id: r.weight_kg for r in rows}["1001"] == 64.4

    everything = json.dumps(client.get("/api/connections").json()) + str(done.headers) + caplog.text
    for secret in (code, tokens.access, tokens.refresh, wf.CLIENT_SECRET):
        assert secret not in everything

    out = client.delete("/api/connections/withings").json()
    assert out == {"revoked": True, "was_connected": True} and fake.revoked == [USER]
    assert not _card(client)["connected"] and session.get(SyncState, tenant.pk("withings")) is None
    assert len(session.exec(select(BodyComp).where(BodyComp.source == "withings")).all()) == 3  # imported data stays

    done, _, _ = _connect(client, fake)
    assert done.headers["location"].endswith("result=connected") and _card(client)["connected"]


def test_state_forged_replayed_expired_or_for_another_provider_is_refused(client, fake):
    _login(client)
    start = client.post("/api/connections/withings/oauth/start")
    state = httpx.URL(start.json()["authorize_url"]).params["state"]
    code = fake.issue_code(USER)
    assert client.get("/auth/withings/callback", params={"code": code, "state": "not-the-state"}, follow_redirects=False).status_code == 400
    assert client.get("/auth/whoop/callback", params={"code": code, "state": state}, follow_redirects=False).status_code == 400
    ok = client.get("/auth/withings/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert ok.headers["location"].endswith("result=connected")
    client.cookies.set("catch_oauth_withings", start.cookies["catch_oauth_withings"])
    replay = client.get("/auth/withings/callback", params={"code": fake.issue_code(USER), "state": state}, follow_redirects=False)
    assert replay.status_code == 400  # the same state works once


def test_the_state_cookie_is_short_lived_httponly_and_lax(client, fake):
    _login(client)
    cookie = client.post("/api/connections/withings/oauth/start").headers["set-cookie"]
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower() and "Max-Age=600" in cookie and "Path=/" in cookie


def test_denied_expired_code_and_bad_server_setup_each_say_so_and_store_nothing(client, session, fake, monkeypatch):
    _login(client)
    start = client.post("/api/connections/withings/oauth/start")
    state = httpx.URL(start.json()["authorize_url"]).params["state"]
    denied = client.get("/auth/withings/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)
    assert denied.headers["location"].endswith("result=denied")

    expired, _, _ = _connect(client, fake, code="code-that-was-never-issued")
    assert expired.headers["location"].endswith("result=expired")

    fake.secret = "the-real-app-secret-differs"  # what production had: a saved secret that doesn't match the app
    setup, _, _ = _connect(client, fake)
    assert setup.headers["location"].endswith("result=server_setup")
    assert session.get(ProviderConnection, tenant.pk("withings")) is None


def test_an_unregistered_callback_url_is_a_server_setup_problem(client, session, fake, monkeypatch):
    import dataclasses

    monkeypatch.setattr(withings_client, "settings", dataclasses.replace(withings_client.settings, withings_redirect_uri="http://localhost:8787/auth/withings/callback"))
    _login(client)
    start = client.post("/api/connections/withings/oauth/start")
    state = httpx.URL(start.json()["authorize_url"]).params["state"]
    done = client.get("/auth/withings/callback", params={"code": fake.issue_code(USER), "state": state}, follow_redirects=False)
    assert done.headers["location"].endswith("result=server_setup")


def test_a_backfill_problem_after_the_tokens_are_stored_still_reports_connected(client, fake, monkeypatch):
    _login(client)
    monkeypatch.setattr(scheduler, "start_backfill", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("queue down")))
    done, _, _ = _connect(client, fake)
    assert done.headers["location"].endswith("result=connected") and _card(client)["connected"]


def test_an_expired_access_token_is_refreshed_and_the_rotated_refresh_token_saved(session, fake):
    connections.store_oauth(session, "withings", access="stale", refresh="withings-refresh-start", expires_in=-60, account_id=str(USER))
    fake.refresh["withings-refresh-start"] = USER
    token = withings_client.get_access_token(session)
    assert fake.refreshes == 1 and fake.access[token] == USER
    stored = connections.oauth_tokens(session, "withings")
    assert stored.refresh != "withings-refresh-start" and fake.refresh[stored.refresh] == USER  # the new one, persisted
    assert withings_client.get_access_token(session) == token and fake.refreshes == 1  # fresh now: no second refresh


def test_a_revoked_grant_needs_a_reconnect_but_a_bad_app_secret_does_not(session, fake, sync_session):
    connections.store_oauth(session, "withings", access="stale", refresh="refresh-withings-revoked-at-withings", expires_in=-60, account_id=str(USER))
    out = scheduler.run_sync("withings", manual=True)
    assert out.get("needs_reconnect") is True
    assert connections.get(session, "withings").status == connections.NEEDS_RECONNECT

    connections.store_oauth(session, "withings", access="stale", refresh="withings-refresh-good", expires_in=-60, account_id=str(USER))
    fake.refresh["withings-refresh-good"] = USER
    fake.secret = "the-real-app-secret-differs"
    out = scheduler.run_sync("withings", manual=True)
    row = connections.get(session, "withings")
    assert "needs_reconnect" not in out and row.status == connections.ERROR and row.status_detail == "app_misconfigured"
    assert connections.oauth_tokens(session, "withings").refresh == "withings-refresh-good"  # unspent: works once the operator fixes it
    state = session.get(SyncState, tenant.pk("withings"))
    assert "HMAC" not in (state.last_error or "") and "status" not in (state.last_error or "")  # fixed words, not Withings' text (L-48)
    fake.secret = wf.CLIENT_SECRET
    assert scheduler.run_sync("withings", manual=True).get("measures") == 3
    assert connections.get(session, "withings").status == connections.CONNECTED


def test_two_concurrent_refreshes_spend_the_refresh_token_once(tmp_path, fake, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'refresh.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        connections.store_oauth(s, "withings", access="stale", refresh="withings-refresh-shared", expires_in=-60, account_id=str(USER))
    fake.refresh["withings-refresh-shared"] = USER
    slow_post = fake.post

    def post(url, **kw):
        if url == withings_client.OAUTH_URL:
            time.sleep(0.05)  # widen the race window
        return slow_post(url, **kw)

    monkeypatch.setattr(withings_client.httpx, "post", post)
    results, errors = [], []

    def worker():
        try:
            with Session(engine) as s:
                results.append(withings_client.get_access_token(s))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and fake.refreshes == 1 and len(set(results)) == 1


def test_ambiguous_and_account_creation_weigh_ins_are_skipped_and_fat_free_mass_fills_fat(session, fake):
    connections.store_oauth(session, "withings", access="a", refresh="r", expires_in=-60, account_id=str(USER))
    fake.refresh["r"] = USER
    fake.groups[USER] = [
        wf.group(1, NOW - 4000, 70.0, attrib=1),  # shared scale, not attributed to this user
        wf.group(2, NOW - 3000, 71.0, attrib=4),  # typed in at Withings account creation
        wf.group(3, NOW - 2000, 64.0, attrib=2, fat_free_kg=57.6),  # entered by the user in Withings: kept
        wf.group(4, NOW - 1000, 64.2, attrib=0, fat_free_kg=57.0, fat_kg=7.0),  # a direct fat-mass reading wins
    ]
    assert withings_client.sync(session, days=1) == 2
    rows = {r.external_id: r for r in session.exec(select(BodyComp)).all()}
    assert set(rows) == {"3", "4"}
    assert rows["3"].fat_kg == pytest.approx(6.4) and rows["4"].fat_kg == pytest.approx(7.0)


def test_paging_reads_every_group(session, fake):
    connections.store_oauth(session, "withings", access="a", refresh="r", expires_in=-60, account_id=str(USER))
    fake.refresh["r"] = USER
    fake.groups[USER] = [wf.group(i, NOW - i * 3600, 64 + i / 10) for i in range(1, 6)]
    assert withings_client.sync(session, days=2) == 5 and len(fake.measure_calls) == 3


def test_check_app_reports_credentials_and_callback_registration(fake, monkeypatch):
    assert withings_client.check_app() == {"configured": True, "credentials_ok": True, "redirect_uri_registered": True, "error": None}
    assert withings_client.check_app("http://localhost:8787/auth/withings/callback")["redirect_uri_registered"] is False
    fake.secret = "wrong"
    assert withings_client.check_app()["credentials_ok"] is False


def test_account_deletion_revokes_the_withings_grant(session, fake):
    connections.store_oauth(session, "withings", access="a", refresh="r", expires_in=3600, account_id=str(USER))
    connections.revoke_all_for_account_deletion(session)
    assert fake.revoked == [USER] and connections.get(session, "withings") is None


def test_a_failed_revoke_still_disconnects(session, fake):
    connections.store_oauth(session, "withings", access="a", refresh="r", expires_in=3600, account_id=str(USER))
    fake.secret = "wrong"
    assert connections.disconnect_provider(session, "withings") == {"revoked": False, "was_connected": True}
    assert connections.get(session, "withings") is None


def test_status_families_from_the_spec_and_the_live_strings():
    from catch.sync.providers.base import ProviderAuthError, ProviderRateLimited, ProviderUnavailable

    cases = [
        ({"status": 503, "error": "Invalid Params: Invalid HMAC signature"}, withings_client.WithingsAppMisconfigured),
        ({"status": 503, "error": "Invalid Params: invalid redirect_uri"}, withings_client.WithingsAppMisconfigured),
        ({"status": 503, "error": "Invalid Params: invalid code"}, withings_client.WithingsCodeRejected),
        ({"status": 503, "error": "Invalid Params: invalid refresh_token"}, withings_client.WithingsReconnectNeeded),
        ({"status": 401, "error": "XRequestID: Not provided invalid_token: The access token provided is invalid"}, withings_client.WithingsReconnectNeeded),
        ({"status": 100}, ProviderAuthError),
        ({"status": 601}, ProviderRateLimited),
        ({"status": 522}, ProviderUnavailable),
        ({"status": 293}, withings_client.WithingsError),
    ]
    for body, expected in cases:
        with pytest.raises(expected):
            withings_client._check_status(body, "requesttoken")
    # No user token on getnonce/revoke: even an "authentication failed" status there is the app's problem (live: a made-up client id
    # answers 503 "invalid client id/secret").
    for status, error in ((100, None), (401, None), (503, "Invalid Params: invalid client id/secret")):
        for action in ("getnonce", "revoke"):
            with pytest.raises(withings_client.WithingsAppMisconfigured):
                withings_client._check_status({"status": status, "error": error}, action)
    with pytest.raises(withings_client.WithingsError) as plain:
        withings_client._check_status({"status": 293, "error": "Invalid Params"}, "getmeas")
    assert not isinstance(plain.value, (ProviderAuthError, withings_client.WithingsAppMisconfigured))
    withings_client._check_status({"status": 0}, "getmeas")


def test_value_times_ten_to_the_unit_is_exact():
    assert withings_client._real_value({"value": 72400, "unit": -3}) == 72.4
    assert withings_client._real_value({"value": 1820, "unit": -2}) == 18.2
    assert withings_client._real_value({"value": 7, "unit": 1}) == 70.0
