from __future__ import annotations

import json

import httpx
import pytest

from catch.coach.providers.base import ProviderError, VisionRequest
from catch.coach.providers.gemini_provider import GeminiProvider, normalize_usage, sanitize_schema, to_function_declarations, to_gemini_contents
from tests.coach.provider_testkit import NEUTRAL_HISTORY, SECRET, Recorder, collect, json_response, run, sse


def provider_for(route) -> tuple[GeminiProvider, Recorder]:
    rec = Recorder(route)
    return GeminiProvider(SECRET, transport=rec.transport()), rec


def test_key_is_sent_in_a_header_never_in_the_url():
    p, rec = provider_for(lambda r: json_response(200, {"models": [{"name": "models/gemini-x", "displayName": "Gemini X", "supportedGenerationMethods": ["generateContent"]}]}))
    result = run(p.validate())
    assert result["ok"] and result["model_count"] == 1
    req = rec.requests[0]
    assert req.headers["x-goog-api-key"] == SECRET
    assert SECRET not in str(req.url)


def test_list_models_filters_to_generate_content_and_follows_pages():
    pages = {
        None: {"models": [{"name": "models/gemini-a", "supportedGenerationMethods": ["generateContent"]}, {"name": "models/embed-1", "supportedGenerationMethods": ["embedContent"]}], "nextPageToken": "t2"},
        "t2": {"models": [{"name": "models/gemini-b", "displayName": "B", "supportedGenerationMethods": ["generateContent", "countTokens"]}]},
    }
    p, _ = provider_for(lambda r: json_response(200, pages[r.url.params.get("pageToken")]))
    assert [m["id"] for m in run(p.list_models())] == ["gemini-a", "gemini-b"]


@pytest.mark.parametrize(
    "status,body,kind",
    [
        (400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "API key not valid. Please pass a valid API key.", "details": [{"reason": "API_KEY_INVALID"}]}}, "invalid_key"),
        (400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key expired. Please renew the API key."}}, "invalid_key"),
        (403, {"error": {"status": "PERMISSION_DENIED"}}, "invalid_key"),
        (429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for metric"}}, "quota"),
        (503, {"error": {"status": "UNAVAILABLE"}}, "unavailable"),
    ],
)
def test_validate_failures(status, body, kind):
    p, _ = provider_for(lambda r: json_response(status, body))
    result = run(p.validate())
    assert result["ok"] is False and result["kind"] == kind
    assert SECRET not in result["message"]


def test_transport_errors_never_carry_the_key():
    p, _ = provider_for(lambda r: httpx.ConnectTimeout(f"timeout {r.url} {SECRET}"))
    result = run(p.validate())
    assert result["kind"] == "timeout" and SECRET not in json.dumps(result)


def test_sanitize_schema_converts_json_schema_for_the_openapi_subset():
    cleaned = sanitize_schema(
        {"type": "object", "additionalProperties": False, "$ref": "#/x", "properties": {"a": {"type": ["number", "null"]}, "b": {"type": "array", "items": {"type": "string", "additionalProperties": False}}}, "required": ["a"]}
    )
    assert cleaned == {"type": "object", "properties": {"a": {"type": "number", "nullable": True}, "b": {"type": "array", "items": {"type": "string"}}}, "required": ["a"]}


def test_every_coach_tool_converts_without_unsupported_keywords():
    decls = to_function_declarations()
    assert decls and "additionalProperties" not in json.dumps(decls)


def test_function_response_name_is_recovered_from_history_and_signature_roundtrips():
    history = [
        {"role": "user", "blocks": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "blocks": [{"type": "tool_call", "id": "ollama_call_3", "name": "get_load", "input": {"x": 1}, "provider_meta": {"gemini_thought_signature": "SIG"}}]},
        {"role": "user", "blocks": [{"type": "tool_result", "id": "ollama_call_3", "output": "plain text", "is_error": False}]},
    ]
    contents = to_gemini_contents(history)
    assert contents[1]["role"] == "model" and contents[1]["parts"][0] == {"functionCall": {"name": "get_load", "args": {"x": 1}}, "thoughtSignature": "SIG"}
    assert contents[2]["parts"][0] == {"functionResponse": {"name": "get_load", "response": {"output": "plain text"}}}


def test_stream_turn_text_tool_call_usage_and_synthetic_ids():
    chunks = sse(
        {"candidates": [{"content": {"parts": [{"text": "Hello "}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "there"}, {"functionCall": {"name": "get_today", "args": {}}, "thoughtSignature": "S1"}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 100, "cachedContentTokenCount": 40, "candidatesTokenCount": 7, "thoughtsTokenCount": 3}},
    )
    p, rec = provider_for(lambda r: httpx.Response(200, content=chunks))
    events = run(collect(p.stream_turn(system_blocks=[{"text": "SYS"}], messages=NEUTRAL_HISTORY, model="gemini-x")))
    assert "".join(e["text"] for e in events if e["type"] == "text_delta") == "Hello there"
    call = next(e for e in events if e["type"] == "tool_call")
    assert call["id"].startswith("gemini_call_") and call["provider_meta"] == {"gemini_thought_signature": "S1"}
    assert next(e for e in events if e["type"] == "usage")["usage"] == {"input_tokens": 60, "output_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 40}
    assert events[-1]["stop_reason"] == "tool_use"
    req = rec.requests[0]
    assert req.url.path.endswith("/models/gemini-x:streamGenerateContent") and req.url.params["alt"] == "sse"
    assert rec.bodies()[0]["generationConfig"]["maxOutputTokens"] > 0


def test_stream_finish_reasons():
    for reason, stop in (("MAX_TOKENS", "max_tokens"), ("SAFETY", "refusal"), ("STOP", "end_turn")):
        p, _ = provider_for(lambda r, reason=reason: httpx.Response(200, content=sse({"candidates": [{"content": {"parts": [{"text": "x"}]}, "finishReason": reason}]})))
        assert run(collect(p.stream_turn(system_blocks=[{"text": "S"}], messages=NEUTRAL_HISTORY, model="m")))[-1]["stop_reason"] == stop


def test_stream_http_error_is_a_safe_event():
    p, _ = provider_for(lambda r: json_response(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": f"echo {SECRET}"}}))
    events = run(collect(p.stream_turn(system_blocks=[{"text": "S"}], messages=NEUTRAL_HISTORY, model="m")))
    assert events[0]["type"] == "error" and SECRET not in json.dumps(events)


def test_model_id_cannot_inject_a_path():
    p, rec = provider_for(lambda r: json_response(200, {}))
    events = run(collect(p.stream_turn(system_blocks=[{"text": "S"}], messages=NEUTRAL_HISTORY, model="../../v1beta/files")))
    assert events[0]["type"] == "error" and not rec.requests


def test_vision_structured_sends_inline_data_and_parses_json():
    payload = {"candidates": [{"content": {"parts": [{"text": '```json\n{"items": [], "notes": "ok"}\n```'}]}}], "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 2}}
    p, rec = provider_for(lambda r: json_response(200, payload))
    tool = {"name": "t", "description": "d", "input_schema": {"type": "object"}}
    result, usage = run(p.vision_structured("gemini-x", VisionRequest("sys", "look", b"img", "image/png", tool)))
    assert result == {"items": [], "notes": "ok"} and usage["input_tokens"] == 9
    parts = rec.bodies()[0]["contents"][0]["parts"]
    assert parts[1]["inlineData"]["mimeType"] == "image/png"
    assert rec.bodies()[0]["generationConfig"]["responseMimeType"] == "application/json"


def test_vision_bad_output():
    p, _ = provider_for(lambda r: json_response(200, {"candidates": [{"content": {"parts": [{"text": "cannot"}]}}]}))
    with pytest.raises(ProviderError):
        run(p.vision_structured("m", VisionRequest("s", "u", b"x", "image/png", {"name": "t", "description": "d", "input_schema": {}})))


def test_normalize_usage_empty():
    assert normalize_usage(None)["output_tokens"] == 0
