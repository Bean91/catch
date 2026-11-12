"""Provider credentials must never reach a coach tool, the REST tool endpoint, or the MCP server."""

from __future__ import annotations

import asyncio
import json


from catch.api.deps import hash_token
from catch.coach import chat
from catch.coach import settings as cs
from catch.coach import tools
from catch.core.models import AiCredential, ApiToken, CoachConversation
from tests.conftest import TEST_PASSWORD
from tests.test_mcp_principal import _call, _initialize, mounted

KEY = "sk-proj-PLANTED-PROVIDER-KEY-0123456789abcdef"
READ_PREFIXES = ("get_", "list_", "search_", "recall", "predict_")


def _plant(session):
    cs.set_credential(session, "openai", KEY)
    cs.set_credential(session, "gemini", "AIzaPLANTED-GEMINI-KEY-0123456789abcdef")
    cs.update_coach_settings(session, {"provider": "openai", "models": {"openai": "gpt-x"}})
    return [KEY, "AIzaPLANTED-GEMINI-KEY-0123456789abcdef", session.get(AiCredential, ("owner", "openai")).key_enc]


def test_no_tool_is_about_credentials_or_providers():
    for name, spec in tools.TOOLS.items():
        text = (name + " " + spec["description"] + " " + json.dumps(spec["input_schema"])).lower()
        assert not any(w in text for w in ("api_key", "api key", "credential", "secret", "provider key")), name
        assert not name.startswith(("set_provider", "ai_", "provider", "key_"))


def test_every_read_tool_output_is_free_of_planted_keys(session):
    planted = _plant(session)
    for name in tools.TOOLS:
        if not name.startswith(READ_PREFIXES):
            continue
        try:
            dumped = json.dumps(tools.call_tool(session, name, {}))
        except (ValueError, KeyError, TypeError):
            continue  # needs arguments; the schema check above covers its shape
        for secret in planted:
            assert secret not in dumped, f"{name} leaked a provider credential"


def test_memory_block_in_the_system_prompt_has_no_keys(session):
    from catch.coach import memory

    planted = _plant(session)
    block = memory.memory_block(session)
    assert not any(s in block for s in planted)


def test_chat_passes_tools_no_credentials(session, monkeypatch):
    _plant(session)
    seen = []

    def fake_call_tool(session_arg, name, args, ctx=None):
        seen.append(ctx)
        return {"ok": True}

    class P:
        name = "openai"

        def __init__(self):
            self.turn = 0

        async def stream_turn(self, *, system_blocks, messages, model):
            self.turn += 1
            if self.turn == 1:
                yield {"type": "tool_call", "id": "c1", "name": "get_zones", "input": {}}
                yield {"type": "stop", "stop_reason": "tool_use"}
            else:
                yield {"type": "text_delta", "text": "done"}
                yield {"type": "stop", "stop_reason": "end_turn"}

    async def fake_resolve(s, o="owner"):
        return P(), "gpt-x", None, "openai"

    monkeypatch.setattr(tools, "call_tool", fake_call_tool)
    monkeypatch.setattr(chat, "_resolve_provider", fake_resolve)
    conv = CoachConversation()
    session.add(conv)
    session.commit()

    async def go():
        return [e async for e in chat.run_turn(session, conv.id, "hi")]

    asyncio.run(go())
    assert seen and set(seen[0]) == {"conversation_id", "principal", "via"}
    assert KEY not in json.dumps(seen, default=str)


def test_rest_tool_endpoint_and_listing_do_not_expose_keys(client, session):
    planted = _plant(session)
    client.post("/api/login", json={"password": TEST_PASSWORD})
    listing = client.get("/api/coach/tools")
    assert listing.status_code == 200 and not any(s in listing.text for s in planted)
    resp = client.post("/api/coach/tools/get_today", json={"args": {}})
    assert not any(s in resp.text for s in planted)


def test_mcp_mount_never_returns_a_key(session, monkeypatch):
    planted = _plant(session)
    session.add(ApiToken(name="mine", token_hash=hash_token("athlete-tok")))
    session.commit()

    async def go():
        async with mounted(session, monkeypatch) as client:
            h = await _initialize(client, "athlete-tok")
            listed = await client.post("/", headers=h, json={"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
            texts = [listed.text]
            for i, name in enumerate(["get_today", "get_wellness", "recall", "get_zones", "get_load"], start=10):
                out = await _call(client, h, name, {}, rid=i)
                texts.append(json.dumps(out))
            return " ".join(texts)

    blob = asyncio.run(go())
    assert not any(s in blob for s in planted)


def test_sync_errors_with_keys_in_urls_are_scrubbed_before_storage_and_display(session):
    from catch.sync import state

    state.record_error(session, "garmin", f"Client error 403 for url 'https://api.example.test/v1?api_key={KEY}&x=1'")
    from catch.core.models import SyncState

    assert KEY not in session.get(SyncState, "garmin").last_error
