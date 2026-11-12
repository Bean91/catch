from __future__ import annotations

import base64
import json
from typing import AsyncIterator

from catch.coach import tools as tools_module
from catch.coach.providers.base import (
    CONNECT_TIMEOUT_S,
    MAX_OUTPUT_TOKENS,
    READ_TIMEOUT_S,
    ProviderCapabilities,
    ProviderError,
    VisionRequest,
    classify_http_status,
    normalize_tool_ids,
    safe_error_event,
    validation_result,
)

_MAX_TOKENS = MAX_OUTPUT_TOKENS


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out = []
    for msg in normalize_tool_ids(messages):
        content: list[dict] = []
        for block in msg["blocks"]:
            if block["type"] == "text":
                content.append({"type": "text", "text": block["text"]})
            elif block["type"] == "tool_call":
                content.append({"type": "tool_use", "id": block["id"], "name": block["name"], "input": block["input"]})
            elif block["type"] == "tool_result":
                content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(block["output"]),
                        "is_error": block.get("is_error", False),
                    }
                )
        out.append({"role": msg["role"], "content": content})
    return out


def pick_default_sonnet(models: list[dict]) -> str | None:
    """"Default to the current Sonnet" per the task — resolved from the live model list, not
    a hardcoded id, so a future Sonnet release picks itself up without a code change."""
    sonnets = [m for m in models if "sonnet" in m["id"].lower()]
    if not sonnets:
        return None
    sonnets.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return sonnets[0]["id"]


def _usage_dict(usage) -> dict:
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }


def _get(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _supports_image(model) -> bool | None:
    """/v1/models reports `capabilities.image_input.supported` per model; None when the SDK
    version in use doesn't expose it."""
    supported = _get(_get(_get(model, "capabilities"), "image_input"), "supported")
    return supported if isinstance(supported, bool) else None


class AnthropicProvider:
    name = "anthropic"
    capabilities = ProviderCapabilities(streaming=True, tools=True, vision=True)

    def __init__(self, api_key: str):
        # Lazy import: the Pi pays the anthropic SDK's import cost only when the coach is
        # actually used, not on every process start (CLAUDE.md's Pi-memory rule). The key is
        # always passed explicitly — the SDK would otherwise fall back to ANTHROPIC_API_KEY in the
        # environment, which would silently spend someone else's money.
        import anthropic

        self._anthropic = anthropic
        # The SDK rejects httpx.Timeout objects (it brings its own httpx build), so use its own
        # Timeout type, or a plain number if this SDK version doesn't expose one.
        sdk_timeout = getattr(anthropic, "Timeout", None)
        timeout = sdk_timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S) if sdk_timeout else READ_TIMEOUT_S
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=1)

    def _classify(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if type(exc).__name__ == "APITimeoutError":
            return ProviderError("timeout")
        if isinstance(exc, self._anthropic.APIConnectionError):
            return ProviderError("unavailable")
        if isinstance(exc, self._anthropic.AuthenticationError):
            return ProviderError("invalid_key")
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            body = getattr(exc, "body", None) or getattr(exc, "message", "")
            return classify_http_status(status, body)
        return ProviderError("bad_request")

    async def stream_turn(self, *, system_blocks: list[dict], messages: list[dict], model: str) -> AsyncIterator[dict]:
        system_param = [
            {"type": "text", "text": b["text"], **({"cache_control": {"type": "ephemeral"}} if b.get("cache") else {})}
            for b in system_blocks
        ]
        anthropic_messages = _to_anthropic_messages(messages)
        tool_schemas = tools_module.anthropic_tool_schemas()

        try:
            async with self._client.messages.stream(
                model=model,
                max_tokens=_MAX_TOKENS,
                system=system_param,
                tools=tool_schemas,
                messages=anthropic_messages,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield {"type": "text_delta", "text": event.delta.text}
                final = await stream.get_final_message()
        except self._anthropic.APIError as exc:
            yield safe_error_event(self._classify(exc))
            return

        for block in final.content:
            if block.type == "tool_use":
                yield {"type": "tool_call", "id": block.id, "name": block.name, "input": block.input}

        yield {"type": "usage", "usage": _usage_dict(final.usage)}
        yield {"type": "stop", "stop_reason": final.stop_reason}

    async def list_models(self) -> list[dict]:
        out = []
        try:
            async for m in self._client.models.list():
                out.append(
                    {
                        "id": m.id,
                        "display_name": m.display_name,
                        "created_at": str(getattr(m, "created_at", "") or ""),
                        "vision": _supports_image(m),
                    }
                )
        except self._anthropic.APIError as exc:
            raise self._classify(exc) from None
        return out

    async def validate(self) -> dict:
        try:
            # models.list() costs zero tokens — the cheapest possible "is this key valid" probe.
            models = await self.list_models()
        except ProviderError as exc:
            return validation_result(False, exc.kind, exc.user_message)
        return validation_result(True, None, "Connected", len(models))

    async def test_connection(self) -> dict:
        result = await self.validate()
        if result["ok"]:
            return {"ok": True, "model_count": result["model_count"]}
        return {"ok": False, "error": result["message"], "kind": result["kind"]}

    async def vision_structured(self, model: str, req: VisionRequest) -> tuple[dict, dict]:
        image_b64 = base64.standard_b64encode(req.image_bytes).decode()
        tool = {**req.tool, "strict": True}
        try:
            # tool_choice stays "auto": forced tool_choice is rejected outright by some current
            # models, and the system prompt plus `strict` gives the same structured result.
            response = await self._client.messages.create(
                model=model,
                max_tokens=req.max_tokens,
                system=req.system,
                tools=[tool],
                tool_choice={"type": "auto"},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": req.media_type, "data": image_b64}},
                            {"type": "text", "text": req.user_text},
                        ],
                    }
                ],
            )
        except self._anthropic.APIError as exc:
            raise self._classify(exc) from None
        usage = _usage_dict(response.usage)
        block = next((b for b in response.content if b.type == "tool_use" and b.name == req.tool["name"]), None)
        if block is None:
            raise ProviderError("bad_request", "The model didn't return a structured result.")
        return dict(block.input), usage
