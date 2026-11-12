"""OpenAI via the Responses API, over plain httpx (no SDK — the Pi pays for no new dependency
and tests run on httpx.MockTransport).

Why Responses and not Chat Completions: OpenAI's docs say Chat Completions "remains supported,
but Responses is recommended for all new projects", and that some current models require
Responses for tool calling. Request/stream shapes below follow the Responses API reference;
see docs/ai-providers.md for what was and wasn't confirmed against the live docs, and
tests/fixtures/ai/openai_*.json (shaped from those docs, not recorded from a live key).
"""

from __future__ import annotations

import base64
import json
from typing import AsyncIterator

import httpx

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
    strip_code_fence,
    validation_result,
)

BASE_URL = "https://api.openai.com"

# /v1/models returns every model the account can see (embeddings, TTS, image, moderation…) with
# no capability field, so chat-capable models are picked out by id. Anything that doesn't match
# stays reachable by typing the id — this list only decides what the picker offers.
_NON_CHAT_MARKERS = ("embedding", "whisper", "tts", "dall-e", "moderation", "transcribe", "realtime", "audio", "image", "davinci", "babbage", "search", "codex-mini", "computer-use")


def is_chat_model(model_id: str) -> bool:
    mid = model_id.lower()
    looks_like_chat = mid.startswith("gpt-") or mid.startswith("chatgpt") or (mid.startswith("o") and mid[1:2].isdigit())
    return looks_like_chat and not any(m in mid for m in _NON_CHAT_MARKERS)


def to_responses_input(messages: list[dict]) -> list[dict]:
    """Neutral blocks -> Responses input items. No ids are sent (store=false), so a history that
    began on another provider (including Ollama's synthetic call ids) replays cleanly."""
    items: list[dict] = []
    for msg in normalize_tool_ids(messages):
        text_parts: list[str] = []

        def flush():
            if text_parts:
                text = "\n".join(text_parts)
                if msg["role"] == "assistant":
                    items.append({"role": "assistant", "content": [{"type": "output_text", "text": text}]})
                else:
                    items.append({"role": "user", "content": [{"type": "input_text", "text": text}]})
                text_parts.clear()

        for block in msg["blocks"]:
            if block["type"] == "text":
                if block["text"]:
                    text_parts.append(block["text"])
            elif block["type"] == "tool_call":
                flush()
                items.append({"type": "function_call", "call_id": block["id"], "name": block["name"], "arguments": json.dumps(block["input"])})
            elif block["type"] == "tool_result":
                flush()
                items.append({"type": "function_call_output", "call_id": block["id"], "output": json.dumps(block["output"])})
        flush()
    return items


def to_responses_tools() -> list[dict]:
    return [
        {"type": "function", "name": t["name"], "description": t["description"], "parameters": t["input_schema"], "strict": False}
        for t in tools_module.anthropic_tool_schemas()
    ]


def normalize_usage(usage: dict | None) -> dict:
    usage = usage or {}
    cached = ((usage.get("input_tokens_details") or {}).get("cached_tokens")) or 0
    # OpenAI counts cached tokens inside input_tokens; report them separately so the cost math
    # (which prices cache reads on their own rate) doesn't double-count.
    return {
        "input_tokens": max((usage.get("input_tokens") or 0) - cached, 0),
        "output_tokens": usage.get("output_tokens") or 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": cached,
    }


class OpenAIProvider:
    name = "openai"
    capabilities = ProviderCapabilities(streaming=True, tools=True, vision=True)

    def __init__(self, api_key: str, *, base_url: str = BASE_URL, transport: httpx.AsyncBaseTransport | None = None):
        self._api_key = api_key
        self._base_url = base_url
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
            transport=self._transport,
        )

    @staticmethod
    def _error_from(resp: httpx.Response, body: bytes | None = None) -> ProviderError:
        try:
            payload = json.loads(body if body is not None else resp.content)
        except Exception:
            payload = None
        return classify_http_status(resp.status_code, payload)

    @staticmethod
    def _transport_error(exc: Exception) -> ProviderError:
        if isinstance(exc, httpx.TimeoutException):
            return ProviderError("timeout")
        return ProviderError("unavailable")

    async def list_models(self) -> list[dict]:
        try:
            async with self._client() as client:
                resp = await client.get("/v1/models")
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from None
        if resp.status_code != 200:
            raise self._error_from(resp)
        data = (resp.json() or {}).get("data") or []
        models = [m for m in data if isinstance(m.get("id"), str) and is_chat_model(m["id"])]
        models.sort(key=lambda m: m.get("created") or 0, reverse=True)
        return [{"id": m["id"], "display_name": m["id"], "vision": None} for m in models]

    async def validate(self) -> dict:
        try:
            models = await self.list_models()
        except ProviderError as exc:
            return validation_result(False, exc.kind, exc.user_message)
        return validation_result(True, None, "Connected", len(models))

    async def test_connection(self) -> dict:
        result = await self.validate()
        return {"ok": True, "model_count": result["model_count"]} if result["ok"] else {"ok": False, "error": result["message"], "kind": result["kind"]}

    async def stream_turn(self, *, system_blocks: list[dict], messages: list[dict], model: str) -> AsyncIterator[dict]:
        body = {
            "model": model,
            "instructions": "\n\n".join(b["text"] for b in system_blocks),
            "input": to_responses_input(messages),
            "tools": to_responses_tools(),
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "store": False,
            "stream": True,
        }
        tool_calls: list[dict] = []
        usage: dict = {}
        stop = "end_turn"
        try:
            async with self._client() as client:
                async with client.stream("POST", "/v1/responses", json=body) as resp:
                    if resp.status_code != 200:
                        raise self._error_from(resp, await resp.aread())
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload or payload == "[DONE]":
                            continue
                        event = json.loads(payload)
                        kind = event.get("type")
                        if kind == "response.output_text.delta":
                            yield {"type": "text_delta", "text": event.get("delta") or ""}
                        elif kind == "response.output_item.done":
                            item = event.get("item") or {}
                            if item.get("type") == "function_call":
                                args = item.get("arguments") or "{}"
                                tool_calls.append(
                                    {"type": "tool_call", "id": item.get("call_id") or item.get("id"), "name": item.get("name"), "input": json.loads(args) if isinstance(args, str) else args}
                                )
                        elif kind == "response.completed":
                            usage = (event.get("response") or {}).get("usage") or {}
                        elif kind == "response.incomplete":
                            response = event.get("response") or {}
                            usage = response.get("usage") or {}
                            if (response.get("incomplete_details") or {}).get("reason") == "max_output_tokens":
                                stop = "max_tokens"
                            elif (response.get("incomplete_details") or {}).get("reason") == "content_filter":
                                stop = "refusal"
                        elif kind in ("response.failed", "error"):
                            err = event.get("error") or (event.get("response") or {}).get("error") or {}
                            code = str(err.get("code") or err.get("type") or "").lower()
                            if "quota" in code or "credit" in code or "spend_limit" in code:
                                raise ProviderError("quota")
                            if "rate" in code:
                                raise ProviderError("rate_limited")
                            if "overload" in code or "unavailable" in code or "server" in code:
                                raise ProviderError("unavailable")
                            raise ProviderError("bad_request")
        except ProviderError as exc:
            yield safe_error_event(exc)
            return
        except httpx.HTTPError as exc:
            yield safe_error_event(self._transport_error(exc))
            return
        except (json.JSONDecodeError, ValueError):
            yield safe_error_event(ProviderError("bad_request", "The provider sent a response Catch couldn't read."))
            return

        for call in tool_calls:
            yield call
        yield {"type": "usage", "usage": normalize_usage(usage)}
        yield {"type": "stop", "stop_reason": "tool_use" if tool_calls else stop}

    async def vision_structured(self, model: str, req: VisionRequest) -> tuple[dict, dict]:
        data_url = f"data:{req.media_type};base64,{base64.standard_b64encode(req.image_bytes).decode()}"
        schema = req.tool["input_schema"]
        body = {
            "model": model,
            "instructions": req.system,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": req.user_text},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
            "text": {"format": {"type": "json_schema", "name": req.tool["name"], "schema": schema, "strict": True}},
            "max_output_tokens": req.max_tokens,
            "store": False,
        }
        try:
            async with self._client() as client:
                resp = await client.post("/v1/responses", json=body)
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from None
        if resp.status_code != 200:
            raise self._error_from(resp)
        payload = resp.json()
        text = "".join(
            part.get("text", "")
            for item in payload.get("output") or []
            if item.get("type") == "message"
            for part in item.get("content") or []
            if part.get("type") == "output_text"
        )
        try:
            result = json.loads(strip_code_fence(text))
        except json.JSONDecodeError:
            raise ProviderError("bad_request", "The model didn't return a structured result.") from None
        if not isinstance(result, dict):
            raise ProviderError("bad_request", "The model didn't return a structured result.")
        return result, normalize_usage(payload.get("usage"))
