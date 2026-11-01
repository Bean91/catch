from __future__ import annotations

import asyncio
import json

import httpx

from catch.coach.providers.ollama_provider import OllamaProvider


async def _collect(agen):
    return [event async for event in agen]


def _ndjson(*chunks: dict) -> bytes:
    return b"".join((json.dumps(c) + "\n").encode() for c in chunks)


_RealAsyncClient = httpx.AsyncClient


def _patched_async_client(handler):
    """A replacement for httpx.AsyncClient that routes every request through a MockTransport
    — captures the *original* class before patching so the replacement doesn't call itself."""

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_health_check_true_when_reachable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    monkeypatch.setattr(httpx, "AsyncClient", _patched_async_client(handler))
    provider = OllamaProvider("http://laptop.tailnet:11434")
    assert asyncio.run(provider.health_check()) is True


def test_health_check_false_when_unreachable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", _patched_async_client(handler))
    provider = OllamaProvider("http://laptop.tailnet:11434")
    assert asyncio.run(provider.health_check()) is False


def test_stream_turn_emits_text_and_synthesized_tool_call_ids(monkeypatch):
    body = _ndjson(
        {"message": {"role": "assistant", "content": "Looking "}, "done": False},
        {"message": {"role": "assistant", "content": "it up."}, "done": False},
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "get_today", "arguments": {}}}],
            },
            "done": True,
            "prompt_eval_count": 42,
            "eval_count": 7,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(200, content=body)

    monkeypatch.setattr(httpx, "AsyncClient", _patched_async_client(handler))

    provider = OllamaProvider("http://laptop.tailnet:11434")
    events = asyncio.run(
        _collect(
            provider.stream_turn(
                system_blocks=[{"text": "sys", "cache": True}],
                messages=[{"role": "user", "blocks": [{"type": "text", "text": "hi"}]}],
                model="llama3.1",
            )
        )
    )

    text = "".join(e["text"] for e in events if e["type"] == "text_delta")
    assert text == "Looking it up."
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "get_today"
    assert tool_calls[0]["id"]  # synthesized, but present

    usage = next(e for e in events if e["type"] == "usage")
    assert usage["usage"] == {
        "input_tokens": 42,
        "output_tokens": 7,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    assert next(e for e in events if e["type"] == "stop")["stop_reason"] == "tool_use"


def test_stream_turn_reports_unreachable_laptop(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", _patched_async_client(handler))

    provider = OllamaProvider("http://laptop.tailnet:11434")
    events = asyncio.run(
        _collect(provider.stream_turn(system_blocks=[{"text": "sys", "cache": True}], messages=[], model="llama3.1"))
    )
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "laptop awake" in events[0]["message"]


def test_list_models_filters_by_tool_capability(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.1"}, {"name": "tinyllama"}]})
        if request.url.path == "/api/show":
            name = json.loads(request.content)["name"]
            caps = ["completion", "tools"] if name == "llama3.1" else ["completion"]
            return httpx.Response(200, json={"capabilities": caps})
        raise AssertionError(request.url.path)

    monkeypatch.setattr(httpx, "AsyncClient", _patched_async_client(handler))

    provider = OllamaProvider("http://laptop.tailnet:11434")
    models = asyncio.run(provider.list_models())
    assert models == [{"id": "llama3.1", "display_name": "llama3.1"}]
