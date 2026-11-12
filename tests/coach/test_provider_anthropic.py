from __future__ import annotations

import asyncio
import sys
import types

from catch.coach.providers.anthropic_provider import pick_default_sonnet


async def _collect(agen):
    return [event async for event in agen]


class _FakeStreamCtx:
    def __init__(self, events, final_message):
        self._events = events
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for event in self._events:
            yield event

    async def get_final_message(self):
        return self._final_message


class _FakeModelsPager:
    def __init__(self, models):
        self._models = models

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self._models:
            yield m


def _install_fake_anthropic(monkeypatch, *, events, final_message=None, models=(), list_models_error=None):
    capture: list[dict] = []
    client_kwargs: list[dict] = []
    fake_module = types.ModuleType("anthropic")

    class APIError(Exception):
        pass

    class AuthenticationError(APIError):
        pass

    class APIConnectionError(APIError):
        pass

    class APIStatusError(APIError):
        def __init__(self, message, status_code=500):
            super().__init__(message)
            self.status_code = status_code
            self.message = message

    class FakeMessages:
        def stream(self, **kwargs):
            capture.append(kwargs)
            return _FakeStreamCtx(events, final_message)

    class FakeModels:
        def list(self):
            if list_models_error is not None:
                raise list_models_error
            return _FakeModelsPager(models)

    class FakeClient:
        def __init__(self, api_key=None, **kwargs):
            client_kwargs.append({"api_key": api_key, **kwargs})
            self.messages = FakeMessages()
            self.models = FakeModels()

    fake_module.AsyncAnthropic = FakeClient
    fake_module.APIError = APIError
    fake_module.AuthenticationError = AuthenticationError
    fake_module.APIConnectionError = APIConnectionError
    fake_module.APIStatusError = APIStatusError
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    fake_module.client_kwargs = client_kwargs
    return capture, fake_module


def test_stream_turn_emits_tool_call_and_usage_with_cache_tokens(monkeypatch):
    block = types.SimpleNamespace(type="tool_use", id="abc", name="get_today", input={})
    usage = types.SimpleNamespace(input_tokens=10, output_tokens=5, cache_creation_input_tokens=100, cache_read_input_tokens=200)
    final = types.SimpleNamespace(content=[block], usage=usage, stop_reason="tool_use")
    capture, _ = _install_fake_anthropic(monkeypatch, events=[], final_message=final)

    from catch.coach.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider("sk-test")
    system_blocks = [{"text": "SYSTEM PROMPT", "cache": True}, {"text": "MEMORY BLOCK", "cache": False}]
    messages = [{"role": "user", "blocks": [{"type": "text", "text": "hi"}]}]

    events = asyncio.run(
        _collect(provider.stream_turn(system_blocks=system_blocks, messages=messages, model="claude-sonnet-5"))
    )

    assert {"type": "tool_call", "id": "abc", "name": "get_today", "input": {}} in events
    usage_event = next(e for e in events if e["type"] == "usage")
    assert usage_event["usage"] == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 200,
    }
    stop_event = next(e for e in events if e["type"] == "stop")
    assert stop_event["stop_reason"] == "tool_use"

    # Only the static system block carries the cache breakpoint; the volatile memory block
    # (and everything render-ordered after it) must not, or the cache would need to be rebuilt
    # on every turn the memory block changes.
    sent = capture[0]
    assert sent["system"][0] == {"type": "text", "text": "SYSTEM PROMPT", "cache_control": {"type": "ephemeral"}}
    assert sent["system"][1] == {"type": "text", "text": "MEMORY BLOCK"}
    assert sent["tools"]  # tool schemas are present and come before `system` in the request


def test_stream_turn_converts_tool_result_blocks_to_anthropic_shape(monkeypatch):
    usage = types.SimpleNamespace(input_tokens=1, output_tokens=1, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    final = types.SimpleNamespace(content=[], usage=usage, stop_reason="end_turn")
    capture, _ = _install_fake_anthropic(monkeypatch, events=[], final_message=final)

    from catch.coach.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider("sk-test")
    messages = [
        {"role": "user", "blocks": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "blocks": [{"type": "tool_call", "id": "t1", "name": "get_today", "input": {}}]},
        {"role": "user", "blocks": [{"type": "tool_result", "id": "t1", "output": {"ok": True}, "is_error": False}]},
    ]
    asyncio.run(_collect(provider.stream_turn(system_blocks=[{"text": "sys", "cache": True}], messages=messages, model="m")))

    sent_messages = capture[0]["messages"]
    assert sent_messages[1]["content"][0] == {"type": "tool_use", "id": "t1", "name": "get_today", "input": {}}
    assert sent_messages[2]["content"][0]["type"] == "tool_result"
    assert sent_messages[2]["content"][0]["tool_use_id"] == "t1"


def test_pick_default_sonnet_picks_newest_sonnet_by_created_at():
    models = [
        {"id": "claude-opus-5", "created_at": "2026-01-01"},
        {"id": "claude-sonnet-4-6", "created_at": "2025-01-01"},
        {"id": "claude-sonnet-5", "created_at": "2026-06-01"},
    ]
    assert pick_default_sonnet(models) == "claude-sonnet-5"


def test_pick_default_sonnet_none_when_no_sonnet_models():
    assert pick_default_sonnet([{"id": "claude-opus-5", "created_at": "2026-01-01"}]) is None


def test_test_connection_reports_invalid_key(monkeypatch):
    _, fake_module = _install_fake_anthropic(monkeypatch, events=[])

    from catch.coach.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._anthropic = fake_module

    class RaisingModels:
        def list(self):
            raise fake_module.AuthenticationError("bad key")

    class RaisingClient:
        models = RaisingModels()

    provider._client = RaisingClient()
    result = asyncio.run(provider.test_connection())
    assert result["ok"] is False and result["kind"] == "invalid_key"


def test_real_sdk_accepts_the_timeout_and_never_reads_the_environment_key(monkeypatch):
    """Not the fake module: the installed SDK has its own httpx build and rejects httpx.Timeout."""
    import importlib

    monkeypatch.undo()
    sys.modules.pop("anthropic", None)
    importlib.import_module("anthropic")
    from catch.coach.providers.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-ENV-KEY-MUST-NOT-BE-USED-000000")
    provider = AnthropicProvider("sk-ant-explicit-key-0123456789abcdef")
    assert provider._client.api_key == "sk-ant-explicit-key-0123456789abcdef"


def test_error_classification_for_invalid_expired_rate_limited_and_billing(monkeypatch):
    from catch.coach.providers.anthropic_provider import AnthropicProvider

    _, module = _install_fake_anthropic(monkeypatch, events=[])
    provider = AnthropicProvider("sk-test")
    api_status = module.APIStatusError
    assert provider._classify(module.AuthenticationError("bad")).kind == "invalid_key"
    assert provider._classify(api_status("forbidden", status_code=403)).kind == "invalid_key"
    assert provider._classify(api_status("billing", status_code=402)).kind == "quota"
    assert provider._classify(api_status("slow down", status_code=429)).kind == "rate_limited"
    assert provider._classify(api_status("overloaded", status_code=529)).kind == "unavailable"
    assert provider._classify(module.APIConnectionError("net")).kind == "unavailable"
    assert provider._classify(module.APIError("???")).kind == "bad_request"


def test_stream_error_event_carries_no_provider_text(monkeypatch):
    from catch.coach.providers.anthropic_provider import AnthropicProvider

    _, module = _install_fake_anthropic(monkeypatch, events=[])
    provider = AnthropicProvider("sk-test")

    class Boom:
        def stream(self, **kwargs):
            raise module.AuthenticationError("invalid x-api-key sk-ant-LEAKED-KEY-0123456789")

    provider._client.messages = Boom()
    events = asyncio.run(_collect(provider.stream_turn(system_blocks=[{"text": "s"}], messages=[{"role": "user", "blocks": [{"type": "text", "text": "hi"}]}], model="m")))
    assert events[0]["kind"] == "invalid_key" and "LEAKED" not in str(events)


def test_list_models_reports_per_model_image_support(monkeypatch):
    from catch.coach.providers.anthropic_provider import AnthropicProvider

    caps = types.SimpleNamespace(image_input=types.SimpleNamespace(supported=True))
    models = [types.SimpleNamespace(id="claude-a", display_name="A", created_at="2026-01-01", capabilities=caps), types.SimpleNamespace(id="claude-b", display_name="B", created_at="2026-01-02")]
    _install_fake_anthropic(monkeypatch, events=[], models=models)
    provider = AnthropicProvider("sk-test")
    listed = asyncio.run(provider.list_models())
    assert [m["vision"] for m in listed] == [True, None]
