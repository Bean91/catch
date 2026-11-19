"""Device tokens (session 28): least-privilege scope, expiry, a cap, revoke-all, and the sharing endpoints being cookie-only."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import TEST_PASSWORD
from sqlmodel import Session, select

from catch.coach import limits
from catch.core.models import ApiToken


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _mint(client, **body):
    limits._windows.clear()
    resp = client.post("/api/coach/tokens", json={"name": "laptop", **body})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _bearer(token):
    return {"authorization": f"Bearer {token['token']}"}


def test_a_new_athlete_token_is_read_only_and_expires(client):
    _login(client)
    t = _mint(client)
    assert t["scope"] == "read"
    days = (datetime.fromisoformat(t["expires_at"]).replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
    assert 88 <= days <= 90


def test_a_read_token_reads_but_cannot_write_even_with_confirm(client):
    _login(client)
    t = _mint(client, scope="read")
    client.cookies.clear()
    assert client.post("/api/coach/tools/get_zones", headers=_bearer(t), json={"args": {}}).status_code == 200
    denied = client.post("/api/coach/tools/add_note", headers=_bearer(t), json={"args": {"date": "2026-11-02", "text": "x", "confirm": True}})
    assert denied.status_code == 422 and "scope" in denied.json()["detail"]


def test_a_write_token_can_preview_and_then_confirm(client):
    _login(client)
    t = _mint(client, scope="write")
    client.cookies.clear()
    args = {"date": "2026-11-02", "text": "easy 60"}
    preview = client.post("/api/coach/tools/add_note", headers=_bearer(t), json={"args": args}).json()
    assert preview["saved"] is False
    saved = client.post("/api/coach/tools/add_note", headers=_bearer(t), json={"args": {**args, "confirm": True}})
    assert saved.status_code == 200 and saved.json()["text"] == "easy 60"


def test_an_expired_token_stops_working(client, engine):
    _login(client)
    t = _mint(client)
    with Session(engine) as s:
        row = s.exec(select(ApiToken)).first()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.add(row)
        s.commit()
    client.cookies.clear()
    assert client.post("/api/coach/tools/get_zones", headers=_bearer(t), json={"args": {}}).status_code == 401


def test_active_tokens_are_capped_and_expired_ones_do_not_count(client, engine):
    _login(client)
    for _ in range(10):
        _mint(client)
    limits._windows.clear()
    assert client.post("/api/coach/tokens", json={"name": "one too many"}).status_code == 409
    with Session(engine) as s:
        row = s.exec(select(ApiToken)).first()
        row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        s.add(row)
        s.commit()
    limits._windows.clear()
    assert client.post("/api/coach/tokens", json={"name": "fits now"}).status_code == 200


def test_revoking_all_tokens_kills_them_at_once(client):
    _login(client)
    tokens = [_mint(client), _mint(client)]
    limits._windows.clear()
    assert client.request("DELETE", "/api/coach/tokens").json() == {"revoked": 2}
    client.cookies.clear()
    for t in tokens:
        assert client.post("/api/coach/tools/get_zones", headers=_bearer(t), json={"args": {}}).status_code == 401


def test_a_coach_token_defaults_to_write_but_only_reaches_the_coaching_tools(client):
    _login(client)
    t = _mint(client, role="coach", display_name="Coach Sam")
    assert t["scope"] == "write"
    client.cookies.clear()
    assert client.post("/api/coach/tools/get_zones", headers=_bearer(t), json={"args": {}}).status_code == 403


def test_bad_token_requests_are_refused(client):
    _login(client)
    limits._windows.clear()
    assert client.post("/api/coach/tokens", json={"name": "x", "scope": "admin"}).status_code == 422
    assert client.post("/api/coach/tokens", json={"name": "", "scope": "read"}).status_code == 422
    assert client.post("/api/coach/tokens", json={"name": "x", "expires_in_days": 9999}).status_code == 422


def test_a_device_token_can_not_reach_the_sharing_settings(client):
    _login(client)
    t = _mint(client, scope="write")
    client.cookies.clear()
    assert client.get("/api/ai/sharing", headers=_bearer(t)).status_code == 401
    assert client.put("/api/ai/sharing", headers=_bearer(t), json={"acknowledge": True}).status_code == 401


@pytest.mark.real_ai_sharing
def test_the_sharing_endpoints_round_trip(client):
    _login(client)
    start = client.get("/api/ai/sharing").json()
    assert start["consented"] is False and all(c["enabled"] is False for c in start["categories"])
    bad = client.put("/api/ai/sharing", json={"categories": {"wellness": True}})
    assert bad.status_code == 422
    ok = client.put("/api/ai/sharing", json={"acknowledge": True, "categories": {"wellness": True}}).json()
    assert ok["consented"] is True and next(c for c in ok["categories"] if c["key"] == "wellness")["enabled"] is True
    youth = client.put("/api/ai/sharing", json={"age_band": "u15", "categories": {"nutrition": True}})
    assert youth.status_code == 422 and "guardian" in youth.json()["detail"]
    gone = client.delete("/api/ai/sharing").json()
    assert gone["consented"] is False and not any(c["enabled"] for c in gone["categories"])
