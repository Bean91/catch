from __future__ import annotations

import asyncio

from sqlmodel import select

from catch.coach import chat
from catch.coach.providers.base import ProviderError
from catch.core.models import CoachConversation, CoachMessage


class FakeProvider:
    name = "anthropic"

    def __init__(self, turns: list[list[dict]]):
        self._turns = turns
        self.calls: list[dict] = []

    async def stream_turn(self, *, system_blocks, messages, model):
        self.calls.append({"system_blocks": system_blocks, "messages": [dict(m) for m in messages], "model": model})
        for event in self._turns.pop(0):
            yield event


async def _collect(agen):
    return [event async for event in agen]


def _new_conversation(session) -> int:
    conv = CoachConversation()
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv.id


def test_run_turn_executes_tool_call_then_returns_text(session, monkeypatch):
    conv_id = _new_conversation(session)
    prices = {"input": 1.0, "output": 2.0, "cache_write": 3.0, "cache_read": 4.0}
    provider = FakeProvider(
        [
            [
                {"type": "tool_call", "id": "t1", "name": "get_zones", "input": {}},
                {"type": "usage", "usage": {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
                {"type": "stop", "stop_reason": "tool_use"},
            ],
            [
                {"type": "text_delta", "text": "Here's "},
                {"type": "text_delta", "text": "your answer."},
                {"type": "usage", "usage": {"input_tokens": 150, "output_tokens": 10, "cache_creation_input_tokens": 500, "cache_read_input_tokens": 2000}},
                {"type": "stop", "stop_reason": "end_turn"},
            ],
        ]
    )

    async def fake_resolve(session_arg, owner_id="owner"):
        return provider, "claude-sonnet-5", prices, "anthropic"

    monkeypatch.setattr(chat, "_resolve_provider", fake_resolve)

    events = asyncio.run(_collect(chat.run_turn(session, conv_id, "how should I train today?")))

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert tool_calls and tool_calls[0]["name"] == "get_zones"
    assert tool_results and tool_results[0]["is_error"] is False
    assert "".join(e["text"] for e in events if e["type"] == "text") == "Here's your answer."
    assert events[-1]["type"] == "done"

    # Cost includes cache read/write tokens, not just input/output.
    usage_events = [e for e in events if e["type"] == "usage"]
    assert len(usage_events) == 2
    second_cost = usage_events[1]["cost_usd"]
    expected = (150 * 1.0 + 10 * 2.0 + 500 * 3.0 + 2000 * 4.0) / 1_000_000
    assert abs(second_cost - expected) < 1e-9

    # Tool execution loops back into the next turn's message history as a tool_result block.
    second_call_messages = provider.calls[1]["messages"]
    assert second_call_messages[-1]["blocks"][0]["type"] == "tool_result"

    # Both turns persisted.
    rows = session.exec(select(CoachMessage).where(CoachMessage.conversation_id == conv_id)).all()
    assert len(rows) == 4  # user, assistant(tool_call), user(tool_result), assistant(text)


def test_run_turn_blocks_when_daily_cap_already_reached(session, monkeypatch):
    conv_id = _new_conversation(session)
    session.add(CoachMessage(conversation_id=conv_id, role="assistant", blocks_json="[]", cost_usd=5.0))
    session.commit()

    from catch.coach import settings as coach_settings_module

    coach_settings_module.update_coach_settings(session, {"daily_cap_usd": 1.0})

    called = False

    async def fake_resolve(session_arg, owner_id="owner"):
        nonlocal called
        called = True
        raise AssertionError("provider should never be resolved once the cap is hit")

    monkeypatch.setattr(chat, "_resolve_provider", fake_resolve)

    events = asyncio.run(_collect(chat.run_turn(session, conv_id, "hi")))
    assert events == [{"type": "cap_reached", "reason": "usd", "daily_spend_usd": 5.0, "daily_cap_usd": 1.0}]
    assert called is False


def test_run_turn_checks_cap_between_tool_iterations(session, monkeypatch):
    """The cap must be re-checked every loop iteration, not only once per user turn."""
    conv_id = _new_conversation(session)
    from catch.coach import settings as coach_settings_module

    coach_settings_module.update_coach_settings(session, {"daily_cap_usd": 0.000001})

    provider = FakeProvider(
        [
            [
                {"type": "tool_call", "id": "t1", "name": "get_zones", "input": {}},
                {"type": "usage", "usage": {"input_tokens": 1000, "output_tokens": 1000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
                {"type": "stop", "stop_reason": "tool_use"},
            ]
        ]
    )

    async def fake_resolve(session_arg, owner_id="owner"):
        return provider, "claude-sonnet-5", {"input": 1.0, "output": 1.0, "cache_write": 1.0, "cache_read": 1.0}, "anthropic"

    monkeypatch.setattr(chat, "_resolve_provider", fake_resolve)

    events = asyncio.run(_collect(chat.run_turn(session, conv_id, "hi")))
    assert events[-1]["type"] == "cap_reached"
    assert len(provider.calls) == 1  # never got to loop a second time


def test_run_turn_surfaces_provider_resolution_errors(session, monkeypatch):
    conv_id = _new_conversation(session)

    async def fake_resolve(session_arg, owner_id="owner"):
        raise ProviderError("bad_request", "No Anthropic model is selected. Pick one in Settings → AI Providers.")

    monkeypatch.setattr(chat, "_resolve_provider", fake_resolve)

    events = asyncio.run(_collect(chat.run_turn(session, conv_id, "hi")))
    assert events == [{"type": "error", "kind": "bad_request", "message": "No Anthropic model is selected. Pick one in Settings → AI Providers.", "switch_to": []}]


def test_run_turn_stops_after_max_tool_iterations(session, monkeypatch):
    conv_id = _new_conversation(session)
    looping_turn = [
        {"type": "tool_call", "id": "t", "name": "get_zones", "input": {}},
        {"type": "usage", "usage": {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
        {"type": "stop", "stop_reason": "tool_use"},
    ]
    provider = FakeProvider([list(looping_turn) for _ in range(chat._MAX_TOOL_ITERATIONS)])

    async def fake_resolve(session_arg, owner_id="owner"):
        return provider, "claude-sonnet-5", {}, "anthropic"

    monkeypatch.setattr(chat, "_resolve_provider", fake_resolve)

    events = asyncio.run(_collect(chat.run_turn(session, conv_id, "hi")))
    assert events[-1] == {"type": "error", "message": "Stopped after too many tool calls in one turn."}
    assert len(provider.calls) == chat._MAX_TOOL_ITERATIONS
