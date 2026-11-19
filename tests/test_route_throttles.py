"""Session 28: the sensitive routes that had no throttle at all now answer 429 after their bucket's ceiling."""

import pytest
from conftest import TEST_PASSWORD

from catch.coach import limits


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


@pytest.fixture(autouse=True)
def _clean():
    limits._windows.clear()
    yield
    limits._windows.clear()


def _hammer(call, ceiling):
    codes = [call().status_code for _ in range(ceiling + 3)]
    assert 429 in codes, codes
    assert codes.index(429) <= ceiling + 1


def test_token_minting_is_throttled(client):
    _login(client)
    _hammer(lambda: client.post("/api/coach/tokens", json={"name": "t"}), limits.BUCKET_LIMITS["token"])


def test_the_tool_endpoint_is_throttled(client):
    _login(client)
    limits.BUCKET_LIMITS["tool"], saved = 5, limits.BUCKET_LIMITS["tool"]
    try:
        _hammer(lambda: client.post("/api/coach/tools/get_today", json={"args": {}}), 5)
    finally:
        limits.BUCKET_LIMITS["tool"] = saved


def test_nutrition_lookups_are_throttled(client, monkeypatch):
    _login(client)
    from catch.sync import nutrition

    monkeypatch.setattr(nutrition, "search_foods", lambda *a, **k: [])
    _hammer(lambda: client.get("/api/nutrition/search", params={"q": "oats"}), limits.BUCKET_LIMITS["lookup"])


def test_the_unauthenticated_callback_is_throttled_per_address(client):
    _hammer(lambda: client.get("/auth/whoop/callback", params={"error": "x"}, follow_redirects=False), limits.BUCKET_LIMITS["callback"])


def test_a_429_says_when_to_retry(client):
    _login(client)
    for _ in range(limits.BUCKET_LIMITS["token"] + 1):
        r = client.post("/api/coach/tokens", json={"name": "t"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
