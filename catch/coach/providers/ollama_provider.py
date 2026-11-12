from __future__ import annotations

import base64
import json
import uuid
from typing import Any, AsyncIterator

import httpx

from catch.coach import tools as tools_module
from catch.coach.providers.base import (
    MAX_OUTPUT_TOKENS,
    ProviderCapabilities,
    ProviderError,
    VisionRequest,
    safe_error_event,
    strip_code_fence as _base_strip_code_fence,
    validation_result,
)

_HEALTH_TIMEOUT_S = 2.5


def _to_ollama_messages(messages: list[dict]) -> list[dict]:
    """Ollama's native tool calling speaks OpenAI-shaped chat messages. Tool results have no
    tool_call_id round-trip in Ollama's wire format — content is matched back up by the model
    reading the conversation in order, not by id — so we just emit role "tool" in sequence."""
    out = []
    for msg in messages:
        text_parts = [b["text"] for b in msg["blocks"] if b["type"] == "text"]
        tool_calls = [b for b in msg["blocks"] if b["type"] == "tool_call"]
        tool_results = [b for b in msg["blocks"] if b["type"] == "tool_result"]

        if msg["role"] == "assistant" and (text_parts or tool_calls):
            entry: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts)}
            if tool_calls:
                entry["tool_calls"] = [{"function": {"name": tc["name"], "arguments": tc["input"]}} for tc in tool_calls]
            out.append(entry)
        elif text_parts:
            out.append({"role": msg["role"], "content": "\n".join(text_parts)})

        for tr in tool_results:
            out.append({"role": "tool", "content": json.dumps(tr["output"])})
    return out


def _strip_code_fence(text: str) -> str:
    """Strips a leading/trailing markdown code fence (```` ``` ```` or ```` ```json ````) if
    present. qwen2.5-coder:14b was observed, live, wrapping a raw tool-call blob this way on
    one turn and emitting bare JSON (no fence at all) on another — same model, same kind of
    question, two different shapes — so both are handled rather than just the first one seen."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    first_newline = stripped.find("\n")
    body = stripped[first_newline + 1 :] if first_newline != -1 else stripped[3:]
    if body.endswith("```"):
        body = body[:-3]
    return body.strip()


def _parse_raw_tool_call(text: str) -> dict | None:
    """Some models Ollama itself reports as `"tools": true` capable don't actually populate
    the native `tool_calls` field — observed live with qwen2.5-coder:14b, which instead
    streamed a `{"name": "get_today", "arguments": {}}`-shaped blob as plain `content`
    (bare, or inside a ```` ```json ```` fence — see _strip_code_fence), token by token.
    Only called on a buffered blob that never resolved to real text (see stream_turn) and
    only trusted if `name` is a real tool — never acts on an arbitrary `{...}`-shaped answer."""
    try:
        obj = json.loads(_strip_code_fence(text))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("name")
    if name not in tools_module.TOOLS:
        return None
    arguments = obj.get("arguments", obj.get("parameters", {}))
    if not isinstance(arguments, dict):
        return None
    return {"name": name, "input": arguments}


class OllamaProvider:
    name = "ollama"
    # Vision depends on the selected model (a "vision" entry in /api/show's capabilities), so the
    # provider-level flag is True and the per-model flag from list_models() narrows it.
    capabilities = ProviderCapabilities(streaming=True, tools=True, vision=True)

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    def _synthetic_id(self) -> str:
        # Unique across turns: a per-instance counter restarts every message, so stored histories
        # would hold several different calls under one id.
        return f"ollama_call_{uuid.uuid4().hex[:10]}"

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=_HEALTH_TIMEOUT_S) as client:
                resp = await client.get("/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            # A sleeping laptop over Tailscale times out rather than refusing the connection —
            # either way, that's "unavailable," not an exception the caller should see.
            return False

    async def stream_turn(self, *, system_blocks: list[dict], messages: list[dict], model: str) -> AsyncIterator[dict]:
        if not await self.health_check():
            yield safe_error_event(ProviderError("unavailable", "Ollama isn't reachable at the configured URL. Is the laptop awake?"))
            return

        system_text = "\n\n".join(b["text"] for b in system_blocks)
        ollama_messages = [{"role": "system", "content": system_text}, *_to_ollama_messages(messages)]

        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    "/api/chat",
                    json={
                        "model": model,
                        "messages": ollama_messages,
                        "tools": tools_module.ollama_tool_schemas(),
                        "stream": True,
                        "options": {"num_predict": MAX_OUTPUT_TOKENS},
                    },
                ) as resp:
                    resp.raise_for_status()
                    tool_calls_seen: list[dict] = []
                    final_chunk: dict = {}
                    # Holds content back instead of streaming it live until the first non-
                    # whitespace character decides whether this looks like a raw tool-call JSON
                    # blob — bare ("{") or markdown-fenced ("```") — rather than prose; see
                    # _parse_raw_tool_call below. A normal answer decides "not buffering" on its
                    # first character and streams live from then on, same as before; only
                    # content opening with "{" or "```" pays the cost of being held back (and
                    # only until the stream ends).
                    content_buffer = ""
                    decided = False
                    buffering = False
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        message = chunk.get("message") or {}
                        piece = message.get("content") or ""
                        if piece:
                            if buffering:
                                content_buffer += piece
                            elif not decided:
                                content_buffer += piece
                                if content_buffer.strip():
                                    decided = True
                                    lstripped = content_buffer.lstrip()
                                    buffering = lstripped.startswith("{") or lstripped.startswith("```")
                                    if not buffering:
                                        yield {"type": "text_delta", "text": content_buffer}
                                        content_buffer = ""
                                # else: still entirely whitespace — keep waiting before deciding
                            else:
                                yield {"type": "text_delta", "text": piece}
                        for tc in message.get("tool_calls") or []:
                            fn = tc.get("function", {})
                            arguments = fn.get("arguments", {})
                            if isinstance(arguments, str):
                                arguments = json.loads(arguments) if arguments else {}
                            call = {"type": "tool_call", "id": self._synthetic_id(), "name": fn.get("name"), "input": arguments}
                            tool_calls_seen.append(call)
                        if chunk.get("done"):
                            final_chunk = chunk
        except httpx.HTTPError as exc:
            # Not str(exc): httpx's text carries the request URL, which can hold user:pass@ from
            # a user-entered base URL.
            kind = "timeout" if isinstance(exc, httpx.TimeoutException) else "unavailable"
            yield safe_error_event(ProviderError(kind, "Ollama request failed. Is the laptop awake and the URL right?"))
            return

        if content_buffer:
            parsed = _parse_raw_tool_call(content_buffer) if not tool_calls_seen else None
            if parsed is not None:
                tool_calls_seen.append({"type": "tool_call", "id": self._synthetic_id(), **parsed})
            else:
                # Either it didn't parse as a tool call after all (just prose that happened to
                # start with "{"), or the model already made a real tool call separately —
                # either way, don't silently drop real content.
                yield {"type": "text_delta", "text": content_buffer}

        for call in tool_calls_seen:
            yield call

        yield {
            "type": "usage",
            "usage": {
                "input_tokens": final_chunk.get("prompt_eval_count") or 0,
                "output_tokens": final_chunk.get("eval_count") or 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        }
        yield {"type": "stop", "stop_reason": "tool_use" if tool_calls_seen else "end_turn"}

    async def list_models(self) -> list[dict]:
        if not await self.health_check():
            return []
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            tags = (await client.get("/api/tags")).json()
            out = []
            for m in tags.get("models", []):
                try:
                    show = (await client.post("/api/show", json={"name": m["name"]})).json()
                except httpx.HTTPError:
                    continue
                # Ollama reports per-model capabilities on /api/show, not /api/tags — only
                # offer models that advertise native tool calling, per the task spec.
                caps = show.get("capabilities") or []
                if "tools" in caps:
                    out.append({"id": m["name"], "display_name": m["name"], "vision": "vision" in caps})
            return out

    async def validate(self) -> dict:
        if not await self.health_check():
            return validation_result(False, "unavailable", "Could not reach Ollama at the configured URL")
        models = await self.list_models()
        return validation_result(True, None, "Connected", len(models))

    async def test_connection(self) -> dict:
        result = await self.validate()
        return {"ok": True, "model_count": result["model_count"]} if result["ok"] else {"ok": False, "error": result["message"], "kind": result["kind"]}

    async def vision_structured(self, model: str, req: VisionRequest) -> tuple[dict, dict]:
        body = {
            "model": model,
            "stream": False,
            "format": req.tool["input_schema"],
            "options": {"num_predict": req.max_tokens},
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user_text, "images": [base64.standard_b64encode(req.image_bytes).decode()]},
            ],
        }
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=120.0) as client:
                resp = await client.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError("timeout" if isinstance(exc, httpx.TimeoutException) else "unavailable") from None
        if resp.status_code != 200:
            raise ProviderError("bad_request", "Ollama couldn't read that image with this model.")
        payload = resp.json()
        try:
            result = json.loads(_base_strip_code_fence((payload.get("message") or {}).get("content") or ""))
        except json.JSONDecodeError:
            raise ProviderError("bad_request", "The model didn't return a structured result.") from None
        if not isinstance(result, dict):
            raise ProviderError("bad_request", "The model didn't return a structured result.")
        usage = {
            "input_tokens": payload.get("prompt_eval_count") or 0,
            "output_tokens": payload.get("eval_count") or 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        return result, usage
