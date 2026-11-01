from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from catch.coach import tools as tools_module

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


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")
        self._next_call_id = 0

    def _synthetic_id(self) -> str:
        self._next_call_id += 1
        return f"ollama_call_{self._next_call_id}"

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
            yield {"type": "error", "message": "Ollama isn't reachable at the configured URL. Is the laptop awake?"}
            return

        system_text = "\n\n".join(b["text"] for b in system_blocks)
        ollama_messages = [{"role": "system", "content": system_text}, *_to_ollama_messages(messages)]

        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    "/api/chat",
                    json={"model": model, "messages": ollama_messages, "tools": tools_module.ollama_tool_schemas(), "stream": True},
                ) as resp:
                    resp.raise_for_status()
                    tool_calls_seen: list[dict] = []
                    final_chunk: dict = {}
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        message = chunk.get("message") or {}
                        if message.get("content"):
                            yield {"type": "text_delta", "text": message["content"]}
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
            yield {"type": "error", "message": f"Ollama request failed: {exc}"}
            return

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
                if "tools" in (show.get("capabilities") or []):
                    out.append({"id": m["name"], "display_name": m["name"]})
            return out

    async def test_connection(self) -> dict:
        if not await self.health_check():
            return {"ok": False, "error": "Could not reach Ollama at the configured URL"}
        models = await self.list_models()
        return {"ok": True, "model_count": len(models)}
