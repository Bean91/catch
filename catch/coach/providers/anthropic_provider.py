from __future__ import annotations

import json
from typing import Any, AsyncIterator

from catch.coach import tools as tools_module

_MAX_TOKENS = 8000


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out = []
    for msg in messages:
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


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str):
        # Lazy import: the Pi pays the anthropic SDK's import cost only when the coach is
        # actually used, not on every process start (CLAUDE.md's Pi-memory rule).
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._anthropic = anthropic

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
            yield {"type": "error", "message": str(exc)}
            return

        for block in final.content:
            if block.type == "tool_use":
                yield {"type": "tool_call", "id": block.id, "name": block.name, "input": block.input}

        usage = final.usage
        yield {
            "type": "usage",
            "usage": {
                "input_tokens": usage.input_tokens or 0,
                "output_tokens": usage.output_tokens or 0,
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            },
        }
        yield {"type": "stop", "stop_reason": final.stop_reason}

    async def list_models(self) -> list[dict]:
        out = []
        async for m in self._client.models.list():
            out.append({"id": m.id, "display_name": m.display_name, "created_at": str(getattr(m, "created_at", "") or "")})
        return out

    async def test_connection(self) -> dict:
        try:
            # models.list() costs zero tokens — the cheapest possible "is this key valid" probe.
            models = await self.list_models()
            return {"ok": True, "model_count": len(models)}
        except self._anthropic.AuthenticationError:
            return {"ok": False, "error": "Invalid API key"}
        except self._anthropic.APIConnectionError:
            return {"ok": False, "error": "Could not reach the Anthropic API"}
        except self._anthropic.APIStatusError as exc:
            return {"ok": False, "error": f"API error ({exc.status_code}): {exc.message}"}
