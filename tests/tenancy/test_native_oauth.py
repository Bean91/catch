"""Session 30 (docs/mobile/oauth-return.md): connecting a provider from the store app. The system browser has no bearer token and
no cookie, so the app asks for a single-use ticket, the browser redeems it (and gets the state cookie there), and the callback
hands control back through the app's custom URL scheme."""

from __future__ import annotations

import dataclasses

import httpx
import pytest

from catch.core import config, oauth_state
from catch.sync import whoop_client as wc
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A = bearer(kit.ALICE)


@pytest.fixture()
def whoop(monkeypatch, pub_client):
    monkeypatch.setattr(wc, "settings", dataclasses.replace(wc.settings, whoop_client_id="cid", whoop_client_secret="cs", whoop_redirect_uri="http://localhost:8000/auth/whoop/callback"))
    pub_client.get("/api/me", headers=A)
    return pub_client


def _ticket_path(client) -> str:
    r = client.post("/api/connections/whoop/oauth/start?native=true", headers=A)
    assert r.status_code == 200, r.text
    url = httpx.URL(r.json()["authorize_url"])
    assert url.path == "/auth/whoop/native-start"  # a ticket URL on THIS server, not the provider
    return f"{url.path}?{url.query.decode()}"


def test_the_whole_native_round_trip_ends_in_the_apps_custom_scheme(whoop, monkeypatch):
    seen = {}

    def fake_exchange(session, code, transport=None):
        seen["code"] = code

    monkeypatch.setattr(wc, "exchange_code", fake_exchange)
    monkeypatch.setattr("catch.sync.scheduler.start_backfill", lambda session, provider: None)
    start = whoop.get(_ticket_path(whoop), follow_redirects=False)  # no Authorization header: this is the system browser
    assert start.status_code == 302
    state = httpx.URL(start.headers["location"]).params["state"]
    assert httpx.URL(start.headers["location"]).host == "api.prod.whoop.com" and len(state) == 8
    assert "catch_oauth_whoop=" in start.headers["set-cookie"] and "HttpOnly" in start.headers["set-cookie"]
    whoop.cookies.set("catch_oauth_whoop", start.cookies["catch_oauth_whoop"])  # Secure cookie: the http test client won't replay it itself
    done = whoop.get("/auth/whoop/callback", params={"code": "AUTHCODE", "state": state}, follow_redirects=False)
    assert done.status_code == 303
    assert done.headers["location"] == f"{config.settings.native_url_scheme}://settings/connections?provider=whoop&result=connected"
    assert seen["code"] == "AUTHCODE"


def test_the_web_flow_still_returns_to_a_page(whoop, monkeypatch):
    monkeypatch.setattr(wc, "exchange_code", lambda session, code, transport=None: None)
    monkeypatch.setattr("catch.sync.scheduler.start_backfill", lambda session, provider: None)
    resp = whoop.post("/api/connections/whoop/oauth/start", headers=A)
    start = resp.json()
    state = httpx.URL(start["authorize_url"]).params["state"]
    assert "/auth/whoop/native-start" not in start["authorize_url"]
    whoop.cookies.set("catch_oauth_whoop", resp.cookies["catch_oauth_whoop"])
    done = whoop.get("/auth/whoop/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert done.headers["location"] == "/settings/connections?provider=whoop&result=connected"


def test_a_ticket_works_once(whoop):
    path = _ticket_path(whoop)
    assert whoop.get(path, follow_redirects=False).status_code == 302
    assert whoop.get(path, follow_redirects=False).status_code == 400


def test_a_ticket_is_bound_to_its_provider_and_to_this_server():
    owner, provider = kit.ALICE, "whoop"
    ticket = oauth_state.make_ticket(owner, provider, "abcdefgh")
    with pytest.raises(oauth_state.OAuthStateError):
        oauth_state.redeem_ticket(ticket, "withings")
    with pytest.raises(oauth_state.OAuthStateError):
        oauth_state.redeem_ticket(ticket + "x", provider)
    with pytest.raises(oauth_state.OAuthStateError):
        oauth_state.redeem_ticket(None, provider)
    assert oauth_state.redeem_ticket(ticket, provider) == (owner, "abcdefgh")


def test_an_expired_ticket_is_refused():
    ticket = oauth_state.make_ticket(kit.ALICE, "whoop", "abcdefgh", now=1_000)
    with pytest.raises(oauth_state.OAuthStateError):
        oauth_state.redeem_ticket(ticket, "whoop", now=1_000 + oauth_state.TICKET_TTL_SECONDS + 1)


def test_a_ticket_cannot_be_used_as_a_state_cookie_and_the_reverse():
    ticket = oauth_state.make_ticket(kit.ALICE, "whoop", "abcdefgh")
    with pytest.raises(oauth_state.OAuthStateError):
        oauth_state.verify(ticket, "whoop", "abcdefgh")  # different key derivation
    cookie = oauth_state.make(kit.ALICE, "whoop", "zzzzzzzz")
    with pytest.raises(oauth_state.OAuthStateError):
        oauth_state.redeem_ticket(cookie, "whoop")


def test_a_forged_callback_with_a_ticket_in_place_of_the_cookie_is_refused(whoop):
    ticket = oauth_state.make_ticket(kit.ALICE, "whoop", "abcdefgh")
    whoop.cookies.set("catch_oauth_whoop", ticket)
    assert whoop.get("/auth/whoop/callback", params={"code": "c", "state": "abcdefgh"}).status_code == 400


def test_native_start_does_not_exist_on_a_personal_deployment(client):
    assert client.get("/auth/whoop/native-start", params={"ticket": "x.y"}, follow_redirects=False).status_code in (400, 404)
