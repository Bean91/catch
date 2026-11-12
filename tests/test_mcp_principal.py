from __future__ import annotations

import contextlib
import json

import httpx
import pytest

from catch.api.deps import hash_token
from catch.core.models import ApiToken
from catch.mcp_server import http_app
from catch.mcp_server.backend import InProcessBackend
from catch.mcp_server.server import build_server

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _parse(resp: httpx.Response) -> dict:
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise AssertionError(resp.text)
    return resp.json()


@contextlib.asynccontextmanager
async def mounted(session, monkeypatch):
    @contextlib.contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(http_app, "get_session", fake_session)
    monkeypatch.setattr("catch.core.db.get_session", fake_session)
    server = build_server(InProcessBackend())
    asgi = server.streamable_http_app(streamable_http_path="/", transport_security=http_app._transport_security())
    app = http_app._BearerAuthMiddleware(asgi)
    async with server.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
            yield client


async def _initialize(client, token):
    h = {**HEADERS, "Authorization": f"Bearer {token}"}
    r = await client.post("/", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})
    assert r.status_code == 200, r.text
    sid = r.headers.get("mcp-session-id")
    h2 = {**h, **({"mcp-session-id": sid} if sid else {}), "mcp-protocol-version": "2025-06-18"}
    await client.post("/", headers=h2, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    return h2


async def _call(client, headers, name, args, rid=2):
    r = await client.post("/", headers=headers, json={"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": args}})
    assert r.status_code == 200, r.text
    return _parse(r)


SECRET = "SECRET-PRIVATE-TEXT"


def _text(out: dict) -> str:
    return "".join(c.get("text", "") for c in out["result"]["content"])


def _seed(session):
    from catch.core.principal import ATHLETE, coach_principal
    from catch.sync import coaching_notes as cn

    session.add(ApiToken(name="mine", token_hash=hash_token("athlete-tok")))
    session.add(ApiToken(name="sam", token_hash=hash_token("coach-tok"), role="coach", display_name="Coach Sam"))
    session.add(ApiToken(name="lee", token_hash=hash_token("coach2-tok"), role="coach", display_name="Coach Lee"))
    session.commit()
    cn.create_technique_note(session, "owner", ATHLETE, {"category": "catch", "text": f"{SECRET} note"})
    cn.create_technique_note(session, "owner", ATHLETE, {"category": "drive", "text": "shared drive note", "visibility": "coach"})
    cn.create_feedback(session, "owner", ATHLETE, {"text": f"{SECRET} feedback", "visibility": "private"})
    cn.create_feedback(session, "owner", coach_principal(0, "x"), {"text": "coach shared line"})


@pytest.mark.anyio
async def test_each_request_sees_its_own_principal_on_the_real_mount(session, monkeypatch):
    _seed(session)
    async with mounted(session, monkeypatch) as client:
        athlete = await _initialize(client, "athlete-tok")
        coach = await _initialize(client, "coach-tok")
        for i in range(3):  # interleaved on one app instance: athlete, coach, athlete, coach...
            a = _text(await _call(client, athlete, "get_technique_notes", {}, rid=10 + i))
            c = _text(await _call(client, coach, "get_technique_notes", {}, rid=20 + i))
            assert SECRET in a and "shared drive note" in a
            assert SECRET not in c and "shared drive note" in c
        assert SECRET in _text(await _call(client, athlete, "get_coach_feedback", {}))
        cf = _text(await _call(client, coach, "get_coach_feedback", {}))
        assert SECRET not in cf and "coach shared line" in cf


@pytest.mark.anyio
async def test_a_coach_token_on_the_athletes_mcp_session_still_gets_coach_access(session, monkeypatch):
    _seed(session)
    async with mounted(session, monkeypatch) as client:
        athlete = await _initialize(client, "athlete-tok")
        hijack = {**athlete, "Authorization": "Bearer coach-tok"}
        out = await _call(client, hijack, "get_technique_notes", {})
        assert SECRET not in json.dumps(out)
        blocked = await _call(client, hijack, "get_today", {})
        assert blocked["result"]["isError"] is True or "error" in blocked


@pytest.mark.anyio
async def test_coach_token_is_limited_to_the_coaching_tools_over_mcp(session, monkeypatch):
    _seed(session)
    async with mounted(session, monkeypatch) as client:
        coach = await _initialize(client, "coach-tok")
        for name, args in (("get_today", {}), ("list_workouts", {}), ("add_technique_note", {"category": "catch", "text": "x", "confirm": True}), ("create_workout_template", {"name": "x", "workout_type": "custom", "description": "d", "confirm": True})):
            out = await _call(client, coach, name, args)
            assert out["result"]["isError"] is True, name  # the SDK masks the reason; REST gives a 403 with it
        ok = await _call(client, coach, "add_coach_feedback", {"text": "Nice rhythm", "confirm": True})
        assert ok["result"]["isError"] is False and json.loads(_text(ok))["saved"] is True
        listing = json.loads(_text(await _call(client, coach, "get_coach_feedback", {"coach": "sam"})))
        assert [f["author"]["name"] for f in listing["feedback"]] == ["Coach Sam"] and listing["feedback"][0]["created_via"] == "mcp"


@pytest.mark.anyio
async def test_missing_or_unknown_token_is_401_and_no_principal_leaks_between_requests(session, monkeypatch):
    _seed(session)
    async with mounted(session, monkeypatch) as client:
        r = await client.post("/", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 401
        r = await client.post("/", headers={**HEADERS, "Authorization": "Bearer nope"}, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 401
        from catch.mcp_server.backend import current_principal

        assert current_principal.get() is None


@pytest.mark.anyio
async def test_the_backend_fails_closed_without_a_principal(session, monkeypatch):
    _seed(session)

    @contextlib.contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr("catch.core.db.get_session", fake_session)
    with pytest.raises(PermissionError):
        await InProcessBackend().call_tool("get_technique_notes", {})
