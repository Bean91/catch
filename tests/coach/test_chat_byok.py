from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from sqlmodel import select

from catch.coach import chat, limits
from catch.coach import settings as cs
from catch.coach.providers import registry
from catch.coach.providers.gemini_provider import GeminiProvider
from catch.coach.providers.openai_provider import OpenAIProvider
from catch.core.models import CoachConversation, CoachMessage
from tests.coach.provider_testkit import SECRET, Recorder, collect, sse


def _conv(session, owner="owner") -> int:
    conv = CoachConversation(owner_id=owner)
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv.id


def _run(session, conv_id, text="hi", owner="owner"):
    return asyncio.run(collect(chat.run_turn(session, conv_id, text, owner)))


def test_no_key_explains_that_ai_needs_a_provider_and_calls_nothing(session):
    conv_id = _conv(session)
    events = _run(session, conv_id)
    assert events[0]["type"] == "ai_not_configured"
    assert "Settings → AI Providers" in events[0]["message"]
    assert len(session.exec(select(CoachMessage)).all()) == 0  # nothing was recorded or sent


def test_invalid_key_is_explained_and_other_providers_offered(session, monkeypatch):
    cs.set_credential(session, "openai", "sk-proj-openai-key-0000000000000001")
    cs.set_credential(session, "gemini", "AIzaGeminiKey000000000000000000001")
    cs.update_coach_settings(session, {"provider": "openai", "models": {"openai": "gpt-x", "gemini": "gemini-x"}})
    rec = Recorder(lambda r: httpx.Response(401, json={"error": {"message": f"Incorrect API key provided: {SECRET}"}}))
    monkeypatch.setattr(registry, "build_provider", lambda s, o, p: OpenAIProvider("k", transport=rec.transport()))
    events = _run(session, _conv(session))
    err = events[0]
    assert err["type"] == "error" and err["kind"] == "invalid_key" and err["switch_to"] == ["gemini"]
    assert SECRET not in json.dumps(events)
    assert cs.masked_credential_info(session, "openai")["status"] == "invalid"


def _history_from_ollama(session, conv_id):
    blocks = [
        ("user", [{"type": "text", "text": "How is my recovery?"}], None),
        ("assistant", [{"type": "text", "text": "Checking."}, {"type": "tool_call", "id": "ollama_call_1", "name": "get_today", "input": {}}], "ollama"),
        ("user", [{"type": "tool_result", "id": "ollama_call_1", "output": {"recovery": 64}, "is_error": False}], None),
        ("assistant", [{"type": "text", "text": "Recovery is 64."}], "ollama"),
    ]
    for role, b, provider in blocks:
        session.add(CoachMessage(conversation_id=conv_id, role=role, blocks_json=json.dumps(b), provider=provider, model="llama" if provider else None))
    session.commit()


def test_switching_to_openai_keeps_history_and_replays_it(session, monkeypatch):
    conv_id = _conv(session)
    _history_from_ollama(session, conv_id)
    cs.set_credential(session, "openai", "sk-proj-openai-key-0000000000000001")
    cs.update_coach_settings(session, {"provider": "openai", "models": {"openai": "gpt-x"}})
    stream = sse({"type": "response.output_text.delta", "delta": "Strain is low."}, {"type": "response.completed", "response": {"usage": {"input_tokens": 50, "output_tokens": 4}}})
    rec = Recorder(lambda r: httpx.Response(200, content=stream))
    monkeypatch.setattr(registry, "build_provider", lambda s, o, p: OpenAIProvider("k", transport=rec.transport()))

    events = _run(session, conv_id, "And strain?")
    assert events[-1]["type"] == "done"
    sent = rec.bodies()[0]["input"]
    assert {"type": "function_call_output", "call_id": "ollama_call_1", "output": json.dumps({"recovery": 64})} in sent
    assert sent[-1]["content"][0]["text"] == "And strain?"

    rows = session.exec(select(CoachMessage).where(CoachMessage.conversation_id == conv_id).order_by(CoachMessage.id)).all()
    assert [r.provider for r in rows if r.role == "assistant"] == ["ollama", "ollama", "openai"]
    assert len(rows) == 6  # nothing deleted by the switch


def test_switching_to_gemini_replays_history_with_function_names(session, monkeypatch):
    conv_id = _conv(session)
    _history_from_ollama(session, conv_id)
    cs.set_credential(session, "gemini", "AIzaGeminiKey000000000000000000001")
    cs.update_coach_settings(session, {"provider": "gemini", "models": {"gemini": "gemini-x"}})
    stream = sse({"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1}})
    rec = Recorder(lambda r: httpx.Response(200, content=stream))
    monkeypatch.setattr(registry, "build_provider", lambda s, o, p: GeminiProvider("k", transport=rec.transport()))
    events = _run(session, conv_id, "next")
    assert events[-1]["type"] == "done"
    contents = rec.bodies()[0]["contents"]
    assert contents[2]["parts"][0]["functionResponse"]["name"] == "get_today"


def test_gemini_thought_signature_is_persisted_on_the_tool_call_block(session, monkeypatch):
    conv_id = _conv(session)
    cs.set_credential(session, "gemini", "AIzaGeminiKey000000000000000000001")
    cs.update_coach_settings(session, {"provider": "gemini", "models": {"gemini": "gemini-x"}})
    turn1 = sse({"candidates": [{"content": {"parts": [{"functionCall": {"name": "get_zones", "args": {}}, "thoughtSignature": "SIG"}]}}]})
    turn2 = sse({"candidates": [{"content": {"parts": [{"text": "done"}]}, "finishReason": "STOP"}]})
    streams = [turn1, turn2]
    rec = Recorder(lambda r: httpx.Response(200, content=streams.pop(0)))
    monkeypatch.setattr(registry, "build_provider", lambda s, o, p: GeminiProvider("k", transport=rec.transport()))
    _run(session, conv_id)
    second = rec.bodies()[1]["contents"]
    assert second[1]["parts"][0]["thoughtSignature"] == "SIG"


def test_unreachable_ollama_offers_the_configured_alternatives(session):
    cs.set_credential(session, "gemini", "AIzaGeminiKey000000000000000000001")
    cs.update_coach_settings(session, {"provider": "ollama", "ollama_base_url": "http://nowhere.invalid:11434", "models": {"ollama": "llama"}})

    class Dead:
        name = "ollama"

        async def health_check(self):
            return False

    registry_build = registry.build_provider
    registry.build_provider = lambda s, o, p: Dead()
    try:
        events = _run(session, _conv(session))
    finally:
        registry.build_provider = registry_build
    assert events[0]["type"] == "provider_unavailable" and events[0]["can_switch_to"] == ["gemini"]


def test_another_owners_conversation_is_not_reachable(session):
    conv_id = _conv(session, owner="alice")
    events = _run(session, conv_id, owner="bob")
    assert events == [{"type": "error", "message": "Conversation not found."}]


def test_message_length_and_rate_limits(session):
    conv_id = _conv(session)
    events = _run(session, conv_id, "x" * (limits.MAX_MESSAGE_CHARS + 1))
    assert events[0]["type"] == "rate_limited"
    for _ in range(limits.REQUESTS_PER_MINUTE):
        _run(session, conv_id)
    assert _run(session, conv_id)[0]["type"] == "rate_limited"
    assert _run(session, _conv(session, owner="someone-else"), owner="someone-else")[0]["type"] == "ai_not_configured"  # per-owner window


def test_concurrent_stream_cap_is_released(session):
    with limits.stream_slot("o"), limits.stream_slot("o"):
        with pytest.raises(limits.LimitExceeded):
            with limits.stream_slot("o"):
                pass
    with limits.stream_slot("o"):
        pass


def test_token_cap_stops_a_turn_even_when_the_model_is_unpriced(session, monkeypatch):
    from catch.coach import cost

    conv_id = _conv(session)
    cs.update_coach_settings(session, {"daily_token_cap": 100})
    cost.record_usage_event(session, "x", {"input_tokens": 80, "output_tokens": 40}, None)
    events = _run(session, conv_id)
    assert events[0]["type"] == "cap_reached" and events[0]["reason"] == "tokens"


def test_unpriced_hosted_model_reports_unknown_cost_not_zero(session, monkeypatch):
    cs.set_credential(session, "openai", "sk-proj-openai-key-0000000000000001")
    cs.update_coach_settings(session, {"provider": "openai", "models": {"openai": "gpt-x"}})
    stream = sse({"type": "response.output_text.delta", "delta": "hi"}, {"type": "response.completed", "response": {"usage": {"input_tokens": 9, "output_tokens": 2}}})
    rec = Recorder(lambda r: httpx.Response(200, content=stream))
    monkeypatch.setattr(registry, "build_provider", lambda s, o, p: OpenAIProvider("k", transport=rec.transport()))
    events = _run(session, _conv(session))
    usage = next(e for e in events if e["type"] == "usage")
    assert usage["cost_usd"] is None and usage["cost_known"] is False


def test_trim_history_drops_whole_old_turns_and_keeps_the_latest():
    big = "x" * 4000
    history = []
    for i in range(6):
        history += [
            {"role": "user", "blocks": [{"type": "text", "text": f"q{i} {big}"}]},
            {"role": "assistant", "blocks": [{"type": "tool_call", "id": f"c{i}", "name": "t", "input": {}}]},
            {"role": "user", "blocks": [{"type": "tool_result", "id": f"c{i}", "output": {}, "is_error": False}]},
            {"role": "assistant", "blocks": [{"type": "text", "text": "a"}]},
        ]
    trimmed = limits.trim_history(history, budget_tokens=2500)
    assert trimmed[0]["role"] == "user" and trimmed[0]["blocks"][0]["type"] == "text"
    assert "q5" in trimmed[0]["blocks"][0]["text"] or len(trimmed) < len(history)
    assert trimmed[-1] is history[-1]
    ids = {b["id"] for m in trimmed for b in m["blocks"] if b["type"] == "tool_call"}
    assert ids == {b["id"] for m in trimmed for b in m["blocks"] if b["type"] == "tool_result"}  # no orphaned pairs
    assert limits.trim_history(history, budget_tokens=10**9) == history


def test_tool_errors_stored_with_the_conversation_are_scrubbed(session, monkeypatch):
    conv_id = _conv(session)
    cs.set_credential(session, "openai", "sk-proj-openai-key-0000000000000001")
    cs.update_coach_settings(session, {"provider": "openai", "models": {"openai": "gpt-x"}})
    stream1 = sse({"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "c1", "name": "get_zones", "arguments": "{}"}})
    stream2 = sse({"type": "response.output_text.delta", "delta": "ok"}, {"type": "response.completed", "response": {"usage": {}}})
    streams = [stream1, stream2]
    rec = Recorder(lambda r: httpx.Response(200, content=streams.pop(0)))
    monkeypatch.setattr(registry, "build_provider", lambda s, o, p: OpenAIProvider("k", transport=rec.transport()))
    from catch.coach import tools

    def boom(*a, **k):
        raise RuntimeError("upstream said Bearer abcdefgh12345678 and ?api_key=TOPSECRET123")

    monkeypatch.setattr(tools, "call_tool", boom)
    _run(session, conv_id)
    stored = " ".join(r.blocks_json for r in session.exec(select(CoachMessage)).all())
    assert "abcdefgh12345678" not in stored and "TOPSECRET123" not in stored
