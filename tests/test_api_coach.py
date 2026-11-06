from __future__ import annotations

import json
from contextlib import contextmanager

from conftest import TEST_PASSWORD

from catch.core.models import CoachConversation


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_tool_endpoints_require_auth(client):
    resp = client.get("/api/coach/tools")
    assert resp.status_code == 401
    resp = client.post("/api/coach/tools/get_today", json={"args": {}})
    assert resp.status_code == 401


def test_tool_endpoints_accept_cookie_auth(client):
    _login(client)
    resp = client.get("/api/coach/tools")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    assert "get_today" in names and "remember" in names

    resp = client.post("/api/coach/tools/get_zones", json={"args": {}})
    assert resp.status_code == 200
    assert "zones" in resp.json()


def test_tool_endpoints_accept_device_bearer_token(client, session):
    _login(client)
    token_resp = client.post("/api/coach/tokens", json={"name": "laptop"})
    raw_token = token_resp.json()["token"]
    client.cookies.clear()  # bearer auth must work with no session cookie at all

    resp = client.post(
        "/api/coach/tools/get_zones", json={"args": {}}, headers={"Authorization": f"Bearer {raw_token}"}
    )
    assert resp.status_code == 200


def test_device_token_does_not_authorize_cookie_only_routes(client):
    _login(client)
    token_resp = client.post("/api/coach/tokens", json={"name": "laptop"})
    raw_token = token_resp.json()["token"]
    client.cookies.clear()

    # A stolen device token must not reach key management, settings, or conversation history.
    for path in ("/api/coach/settings", "/api/coach/conversations", "/api/coach/memory"):
        resp = client.get(path, headers={"Authorization": f"Bearer {raw_token}"})
        assert resp.status_code == 401, path


def test_unknown_tool_name_404s(client):
    _login(client)
    resp = client.post("/api/coach/tools/not_a_real_tool", json={"args": {}})
    assert resp.status_code == 404


def test_create_list_delete_device_tokens(client):
    _login(client)
    created = client.post("/api/coach/tokens", json={"name": "laptop"}).json()
    assert "token" in created

    listed = client.get("/api/coach/tokens").json()
    assert any(t["name"] == "laptop" for t in listed)
    assert "token" not in listed[0]  # raw token is never shown again

    resp = client.delete(f"/api/coach/tokens/{created['id']}")
    assert resp.status_code == 200
    assert client.get("/api/coach/tokens").json() == []


def test_coach_settings_roundtrip_and_key_masking(client):
    _login(client)
    resp = client.get("/api/coach/settings")
    assert resp.json()["anthropic_key"] == {"configured": False, "last4": None}

    client.post("/api/coach/key", json={"api_key": "sk-ant-abcd1234"})
    resp = client.get("/api/coach/settings")
    body = resp.json()
    assert body["anthropic_key"] == {"configured": True, "last4": "1234"}
    assert "sk-ant" not in json.dumps(body)  # the raw key is never sent back to the browser

    resp = client.put("/api/coach/settings", json={"daily_cap_usd": 5.0, "provider": "ollama"})
    assert resp.json()["daily_cap_usd"] == 5.0
    assert resp.json()["provider"] == "ollama"


def test_coach_settings_rejects_bad_patch(client):
    _login(client)
    resp = client.put("/api/coach/settings", json={"provider": "not-a-provider"})
    assert resp.status_code == 422


def test_memory_crud_endpoints(client):
    _login(client)
    fact = client.post("/api/coach/memory/facts", json={"category": "injury", "text": "sore knee"}).json()
    assert fact["ref"].startswith("fact:")

    client.post(
        "/api/coach/memory/events", json={"name": "Club 2k test", "date": "2026-12-01", "type": "2k_test"}
    ).json()
    client.post("/api/coach/memory/goals", json={"text": "Sub 6:40"}).json()

    listing = client.get("/api/coach/memory").json()
    assert any(f["text"] == "sore knee" for f in listing["facts"])
    assert any(e["name"] == "Club 2k test" for e in listing["events"])
    assert any(g["text"] == "Sub 6:40" for g in listing["goals"])

    resp = client.delete(f"/api/coach/memory/{fact['ref']}")
    assert resp.status_code == 200
    resp = client.delete(f"/api/coach/memory/{fact['ref']}")
    assert resp.status_code == 404


def test_conversation_crud(client):
    _login(client)
    conv = client.post("/api/coach/conversations").json()
    assert conv["title"] is None

    listed = client.get("/api/coach/conversations").json()
    assert any(c["id"] == conv["id"] for c in listed)

    fetched = client.get(f"/api/coach/conversations/{conv['id']}").json()
    assert fetched["messages"] == []

    resp = client.delete(f"/api/coach/conversations/{conv['id']}")
    assert resp.status_code == 200
    assert client.get(f"/api/coach/conversations/{conv['id']}").status_code == 404


def test_post_message_streams_sse_events(client, session, engine, monkeypatch):
    _login(client)
    conv = client.post("/api/coach/conversations").json()

    async def fake_run_turn(stream_session, conversation_id, user_text):
        yield {"type": "text", "text": "hello"}
        yield {"type": "done", "stop_reason": "end_turn"}

    monkeypatch.setattr("catch.coach.chat.run_turn", fake_run_turn)

    @contextmanager
    def fake_get_session():
        from sqlmodel import Session

        with Session(engine) as s:
            yield s

    monkeypatch.setattr("catch.api.routes_coach.get_session", fake_get_session)

    resp = client.post(f"/api/coach/conversations/{conv['id']}/messages", json={"text": "hi coach"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = [json.loads(line[len("data: ") :]) for line in resp.text.splitlines() if line.startswith("data: ")]
    assert {"type": "text", "text": "hello"} in events
    assert events[-1] == {"type": "done", "stop_reason": "end_turn"}

    conv_row = session.get(CoachConversation, conv["id"])
    assert conv_row.title == "hi coach"
