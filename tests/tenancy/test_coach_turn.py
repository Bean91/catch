"""A whole coach turn in a public deployment (session 24): the SSE stream, the tool loop, the per-turn memory block, stored
messages and usage accounting — for two users, with a scripted provider standing in for the model."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlmodel import Session

from catch.coach import cost
from catch.coach.providers import registry
from catch.core import tenant
from catch.core.models import CoachMessage
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A, B = bearer(kit.ALICE), bearer(kit.BOB)


class ScriptedProvider:
    """First call: ask for the athlete's memory. Second call (a tool result is in the history): answer by quoting what came back."""

    name = "openai"
    seen_system: list[str] = []

    async def health_check(self):
        return True

    async def stream_turn(self, *, system_blocks, messages, model):
        type(self).seen_system.append("\n".join(b["text"] for b in system_blocks))
        last = messages[-1]["blocks"]
        if any(b["type"] == "tool_result" for b in last):
            output = next(b["output"] for b in last if b["type"] == "tool_result")
            yield {"type": "text_delta", "text": "I see: " + json.dumps(output, default=str)}
            yield {"type": "usage", "usage": {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}
            yield {"type": "stop", "stop_reason": "end_turn"}
        else:
            yield {"type": "tool_call", "id": "call_1", "name": "recall", "input": {"query": ""}}
            yield {"type": "usage", "usage": {"input_tokens": 50, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}
            yield {"type": "stop", "stop_reason": "tool_use"}


@pytest.fixture()
def coach(pub_client, monkeypatch):
    from catch.coach.providers import anthropic_provider, gemini_provider, openai_provider

    async def valid(self):
        return {"ok": True, "kind": None, "message": "Connected", "model_count": 1}

    for cls in (openai_provider.OpenAIProvider, gemini_provider.GeminiProvider, anthropic_provider.AnthropicProvider):
        monkeypatch.setattr(cls, "validate", valid)
    ScriptedProvider.seen_system = []
    monkeypatch.setattr(registry, "build_provider", lambda s, o, p: ScriptedProvider())
    for headers in (A, B):
        pub_client.put("/api/ai/providers/openai/key", headers=headers, json={"api_key": "sk-proj-" + "k" * 30})
        assert pub_client.put("/api/ai/active", headers=headers, json={"provider": "openai", "model": "gpt-x"}).status_code == 200
    return pub_client


def _turn(client, headers, text="what do you know about me?") -> tuple[int, str]:
    conv = client.post("/api/coach/conversations", headers=headers).json()
    with client.stream("POST", f"/api/coach/conversations/{conv['id']}/messages", headers=headers, json={"text": text}) as resp:
        body = "".join(resp.iter_text())
    return conv["id"], body


def test_each_users_turn_sees_only_their_own_memory_and_data(coach, pub_engine):
    for headers, fact in ((A, "ALICE-prefers-morning-sessions"), (B, "BOB-has-a-bad-knee")):
        r = coach.post("/api/coach/tools/remember", headers=headers, json={"args": {"category": "preference", "text": fact, "confirm": True}})
        assert r.status_code == 200, r.text
    ScriptedProvider.seen_system = []
    _, a_body = _turn(coach, A)
    a_system = "\n".join(ScriptedProvider.seen_system)
    ScriptedProvider.seen_system = []
    _, b_body = _turn(coach, B)
    b_system = "\n".join(ScriptedProvider.seen_system)

    assert "ALICE-prefers-morning-sessions" in a_body and "BOB" not in a_body and "BOB" not in a_system
    assert "BOB-has-a-bad-knee" in b_body and "ALICE" not in b_body and "ALICE" not in b_system
    assert '"type": "done"' in a_body or '"type":"done"' in a_body


def test_messages_and_usage_are_stored_under_the_right_owner_and_are_unreadable_to_the_other(coach, pub_engine):
    a_conv, _ = _turn(coach, A)
    b_conv, _ = _turn(coach, B)
    assert coach.get(f"/api/coach/conversations/{a_conv}", headers=B).status_code == 404
    assert coach.post(f"/api/coach/conversations/{a_conv}/messages", headers=B, json={"text": "hi"}).status_code in (200, 404)
    a_msgs = coach.get(f"/api/coach/conversations/{a_conv}", headers=A).json()["messages"]
    assert [m["role"] for m in a_msgs] == ["user", "assistant", "user", "assistant"]  # question, tool call, tool result, answer
    for owner, expected_conv in ((kit.ALICE, a_conv), (kit.BOB, b_conv)):
        with tenant.use_owner(owner), Session(pub_engine) as s:
            assert {m.conversation_id for m in s.execute(select(CoachMessage)).scalars()} == {expected_conv}
            # Spend is read from the owner's own messages: exactly one scripted turn (50+5 then 100+20 tokens), not two users' worth.
            assert cost.today_tokens(s, owner_id=owner) == 175
    # Bob's conversation list and spend are his alone
    assert [c["id"] for c in coach.get("/api/coach/conversations", headers=B).json()] == [b_conv]
    assert coach.get("/api/ai/usage", headers=A).status_code == 200 and coach.get("/api/ai/usage", headers=B).status_code == 200


def test_a_turn_naming_another_users_conversation_is_refused(coach):
    a_conv, _ = _turn(coach, A)
    with coach.stream("POST", f"/api/coach/conversations/{a_conv}/messages", headers=B, json={"text": "read me hers"}) as resp:
        body = "".join(resp.iter_text())
    assert "Conversation not found" in body or resp.status_code == 404
    assert "ALICE" not in body
