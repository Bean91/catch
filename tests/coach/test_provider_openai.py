from __future__ import annotations

import json

import httpx
import pytest

from catch.coach.providers.base import ProviderError, VisionRequest
from catch.coach.providers.openai_provider import OpenAIProvider, is_chat_model, normalize_usage, to_responses_input
from tests.coach.provider_testkit import NEUTRAL_HISTORY, SECRET, Recorder, collect, json_response, run, sse

MODELS_OK = {
    "object": "list",
    "data": [
        {"id": "text-embedding-3-large", "created": 5},
        {"id": "gpt-5-mini", "created": 30},
        {"id": "whisper-1", "created": 1},
        {"id": "o4-mini", "created": 20},
        {"id": "gpt-image-1", "created": 9},
    ],
}


def provider_for(route) -> tuple[OpenAIProvider, Recorder]:
    rec = Recorder(route)
    return OpenAIProvider(SECRET, transport=rec.transport()), rec


def test_validate_valid_key_lists_only_chat_models():
    p, rec = provider_for(lambda r: json_response(200, MODELS_OK))
    result = run(p.validate())
    assert result["ok"] and result["model_count"] == 2
    assert [m["id"] for m in run(p.list_models())] == ["gpt-5-mini", "o4-mini"]
    assert rec.requests[0].headers["authorization"] == f"Bearer {SECRET}"
    assert SECRET not in str(rec.requests[0].url)


@pytest.mark.parametrize(
    "status,body,kind",
    [
        (401, {"error": {"message": "Incorrect API key provided: sk-live-THIS...", "code": "invalid_api_key"}}, "invalid_key"),
        (403, {"error": {"message": "Project does not have access"}}, "invalid_key"),
        (429, {"error": {"code": "insufficient_quota", "type": "insufficient_quota"}}, "quota"),
        (429, {"error": {"code": "credit_balance_exhausted"}}, "quota"),
        (429, {"error": {"code": "rate_limit_exceeded", "type": "rate_limit_error"}}, "rate_limited"),
        (503, {"error": {"type": "service_unavailable_error"}}, "unavailable"),
    ],
)
def test_validate_failures_map_to_a_fixed_kind_without_provider_text(status, body, kind):
    p, _ = provider_for(lambda r: json_response(status, body))
    result = run(p.validate())
    assert result["ok"] is False and result["kind"] == kind
    assert "sk-live" not in result["message"] and "Incorrect API key" not in result["message"]


def test_timeouts_and_connection_errors_are_not_leaked():
    p, _ = provider_for(lambda r: httpx.ReadTimeout(f"timed out for {r.url} with {SECRET}"))
    result = run(p.validate())
    assert result["kind"] == "timeout" and SECRET not in result["message"]
    p, _ = provider_for(lambda r: httpx.ConnectError(f"boom {SECRET}"))
    assert run(p.validate())["kind"] == "unavailable"


def test_is_chat_model():
    assert is_chat_model("gpt-5-mini") and is_chat_model("o3") and is_chat_model("chatgpt-4o-latest")
    assert not is_chat_model("text-embedding-3-small") and not is_chat_model("gpt-image-1") and not is_chat_model("omni-moderation-latest")


def test_history_from_another_provider_replays_into_responses_items():
    items = to_responses_input(NEUTRAL_HISTORY)
    assert items[0] == {"role": "user", "content": [{"type": "input_text", "text": "How was my sleep?"}]}
    assert items[1] == {"role": "assistant", "content": [{"type": "output_text", "text": "Let me check."}]}
    assert items[2] == {"type": "function_call", "call_id": "ollama_call_1", "name": "get_today", "arguments": "{}"}
    assert items[3] == {"type": "function_call_output", "call_id": "ollama_call_1", "output": json.dumps({"recovery": 71})}
    assert items[-1]["role"] == "user"


def test_stream_turn_text_tool_call_and_usage():
    stream = sse(
        {"type": "response.output_text.delta", "delta": "Checking "},
        {"type": "response.output_text.delta", "delta": "now."},
        {"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "call_9", "name": "get_zones", "arguments": "{\"a\": 1}"}},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 1000, "output_tokens": 40, "input_tokens_details": {"cached_tokens": 600}}}},
    )
    p, rec = provider_for(lambda r: httpx.Response(200, content=stream, headers={"content-type": "text/event-stream"}))
    events = run(collect(p.stream_turn(system_blocks=[{"text": "SYS", "cache": True}, {"text": "MEM", "cache": False}], messages=NEUTRAL_HISTORY, model="gpt-5-mini")))
    assert "".join(e["text"] for e in events if e["type"] == "text_delta") == "Checking now."
    assert {"type": "tool_call", "id": "call_9", "name": "get_zones", "input": {"a": 1}} in events
    usage = next(e for e in events if e["type"] == "usage")["usage"]
    assert usage == {"input_tokens": 400, "output_tokens": 40, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 600}
    assert events[-1] == {"type": "stop", "stop_reason": "tool_use"}
    body = rec.bodies()[0]
    assert body["store"] is False and body["stream"] is True and body["max_output_tokens"] > 0
    assert body["instructions"] == "SYS\n\nMEM"
    assert body["tools"] and all(t["type"] == "function" and "name" in t for t in body["tools"])


def test_stream_turn_incomplete_by_max_tokens():
    stream = sse(
        {"type": "response.output_text.delta", "delta": "long"},
        {"type": "response.incomplete", "response": {"incomplete_details": {"reason": "max_output_tokens"}, "usage": {"input_tokens": 5, "output_tokens": 8000}}},
    )
    p, _ = provider_for(lambda r: httpx.Response(200, content=stream))
    events = run(collect(p.stream_turn(system_blocks=[{"text": "S"}], messages=NEUTRAL_HISTORY, model="m")))
    assert events[-1] == {"type": "stop", "stop_reason": "max_tokens"}


@pytest.mark.parametrize("status,kind", [(401, "invalid_key"), (429, "rate_limited"), (500, "unavailable")])
def test_stream_turn_http_errors_become_safe_error_events(status, kind):
    p, _ = provider_for(lambda r: json_response(status, {"error": {"message": f"nope {SECRET}"}}))
    events = run(collect(p.stream_turn(system_blocks=[{"text": "S"}], messages=NEUTRAL_HISTORY, model="m")))
    assert events[0]["type"] == "error" and events[0]["kind"] == kind
    assert SECRET not in json.dumps(events)


def test_stream_failure_event_in_band():
    p, _ = provider_for(lambda r: httpx.Response(200, content=sse({"type": "response.failed", "response": {"error": {"code": "insufficient_quota"}}})))
    events = run(collect(p.stream_turn(system_blocks=[{"text": "S"}], messages=NEUTRAL_HISTORY, model="m")))
    assert events[0]["kind"] == "quota"


def test_vision_structured_uses_strict_json_schema_and_parses_output():
    payload = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"items": [], "notes": "n"}'}]}], "usage": {"input_tokens": 50, "output_tokens": 5}}
    p, rec = provider_for(lambda r: json_response(200, payload))
    tool = {"name": "record_meal_estimate", "description": "d", "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {}}, "notes": {"type": "string"}}, "required": ["items", "notes"], "additionalProperties": False}}
    result, usage = run(p.vision_structured("gpt-5-mini", VisionRequest("sys", "look", b"\xff\xd8img", "image/jpeg", tool)))
    assert result == {"items": [], "notes": "n"} and usage["input_tokens"] == 50
    body = rec.bodies()[0]
    assert body["text"]["format"]["strict"] is True and body["text"]["format"]["name"] == "record_meal_estimate"
    image = body["input"][0]["content"][1]
    assert image["type"] == "input_image" and image["image_url"].startswith("data:image/jpeg;base64,")


def test_vision_with_unparseable_output_is_a_clean_error():
    payload = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "sorry, no"}]}]}
    p, _ = provider_for(lambda r: json_response(200, payload))
    tool = {"name": "t", "description": "d", "input_schema": {"type": "object"}}
    with pytest.raises(ProviderError) as exc:
        run(p.vision_structured("m", VisionRequest("s", "u", b"x", "image/png", tool)))
    assert exc.value.kind == "bad_request"


def test_normalize_usage_handles_missing_fields():
    assert normalize_usage(None)["input_tokens"] == 0
