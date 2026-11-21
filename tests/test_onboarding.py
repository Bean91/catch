"""Session 32: first-run setup — progress persisted per person, resumable, never shown again once done, skipped and failed providers
never block it, and the first import starts without anyone waiting for it."""

from __future__ import annotations

import dataclasses
import time

import httpx
import pytest

from catch.core import oauth_state, tenant
from catch.sync import connections, scheduler
from tests.conftest import TEST_PASSWORD

KEY = "garmin-personal-api-key-abcdefghijklmnop-1234"


def _login(client):
    assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 200


def test_progress_is_saved_and_resumes_then_completion_sticks(client):
    _login(client)
    first = client.get("/api/onboarding").json()
    assert first["state"] == "pending" and first["step"] == 0 and first["steps"][0] == "welcome"
    assert first["show"] is False  # the personal install never sends its owner to setup unprompted
    client.put("/api/onboarding", json={"step": 2, "skipped": ["withings", "whoop", "not-a-provider"]})
    resumed = client.get("/api/onboarding").json()
    assert resumed["step"] == 2 and resumed["skipped"] == ["whoop", "withings"]
    done = client.put("/api/onboarding", json={"complete": True}).json()
    assert done["state"] == "completed" and done["completed_at"]
    assert client.get("/api/onboarding").json()["state"] == "completed"
    # Explicitly restarting from Settings is the only way back.
    again = client.put("/api/onboarding", json={"restart": True}).json()
    assert again["state"] == "pending" and again["step"] == 0


def test_a_new_public_account_is_shown_setup_and_a_completed_one_is_not(session, monkeypatch):
    from catch.api import routes_onboarding as ro
    from catch.core.models import UserProfile

    monkeypatch.setattr(tenant, "is_public", lambda: True)
    fresh = UserProfile(id="owner")  # what the sign-up trigger creates: no onboarding state yet
    assert ro._state(fresh)["show"] is True
    existing = UserProfile(id="owner", onboarding_state="completed")  # migration 0011 marks every existing account completed
    assert ro._state(existing)["show"] is False


def test_start_sync_returns_at_once_and_imports_only_what_is_connected(client, session, monkeypatch):
    _login(client)
    connections.store_credential(session, "garmin", KEY, auth_method="api_key")
    calls = []

    def slow_sync(source, days=3, manual=False):
        time.sleep(0.05)
        calls.append((source, manual))
        return {"source": source}

    monkeypatch.setattr(scheduler, "run_sync", slow_sync)
    out = client.post("/api/onboarding/start-sync").json()
    assert out["started"] == ["garmin"]  # withings/concept2/whoop were skipped: never an error
    assert calls == [("garmin", True)]  # ran after the response, in the background task


def test_start_sync_with_nothing_connected_is_fine(client):
    _login(client)
    assert client.post("/api/onboarding/start-sync").json() == {"started": []}


def test_the_oauth_return_page_is_a_fixed_word_never_a_url(client, monkeypatch):
    from catch.sync import whoop_client as wc

    monkeypatch.setattr(wc, "settings", dataclasses.replace(wc.settings, whoop_client_id="cid", whoop_client_secret="cs", whoop_redirect_uri="http://localhost:8000/auth/whoop/callback"))
    _login(client)
    assert client.post("/api/connections/whoop/oauth/start", params={"return_to": "https://evil.example"}).status_code == 422
    start = client.post("/api/connections/whoop/oauth/start", params={"return_to": "onboarding"}).json()
    state_ = httpx.URL(start["authorize_url"]).params["state"]
    denied = client.get("/auth/whoop/callback", params={"error": "access_denied", "state": state_}, follow_redirects=False)
    # A refused or failed connection comes back to setup with a result the page explains; setup carries on.
    assert denied.status_code == 303 and denied.headers["location"] == "/welcome?provider=whoop&result=denied"


def test_return_to_survives_signing_and_unknown_values_fall_back():
    cookie = oauth_state.make("owner", "whoop", "abcdefgh", return_to="onboarding")
    assert oauth_state.verify_details(cookie, "whoop", "abcdefgh")[2] == "onboarding"
    cookie = oauth_state.make("owner", "whoop", "bcdefghi", return_to="https://evil.example")
    assert oauth_state.verify_details(cookie, "whoop", "bcdefghi")[2] == "connections"


@pytest.mark.parametrize("field", ["onboarding", "timezone", "current_zone", "today"])
def test_me_carries_what_the_app_needs_on_first_load(client, field):
    _login(client)
    assert field in client.get("/api/me").json()
