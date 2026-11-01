from __future__ import annotations

from typing import AsyncIterator, Protocol

# Every provider speaks one normalized event stream, regardless of wire format:
#   {"type": "text_delta", "text": str}
#   {"type": "tool_call", "id": str, "name": str, "input": dict}
#   {"type": "usage", "usage": {"input_tokens", "output_tokens", "cache_creation_input_tokens",
#                                "cache_read_input_tokens"}}
#   {"type": "stop", "stop_reason": "end_turn" | "tool_use" | "max_tokens" | "refusal"}
#   {"type": "error", "message": str}
#
# Messages passed in are provider-neutral blocks, not either provider's wire format (see
# catch/coach/chat.py): [{"role": "user"|"assistant", "blocks": [
#     {"type": "text", "text": str} |
#     {"type": "tool_call", "id": str, "name": str, "input": dict} |
#     {"type": "tool_result", "id": str, "output": Any, "is_error": bool}
# ]}]. Storing (and resuming) conversations in this shape, not Anthropic's or Ollama's native
# one, is what lets a conversation switch providers mid-stream (Ollama laptop asleep ->
# Anthropic) without the stored history being tied to one provider's content-block schema.


class CoachProvider(Protocol):
    name: str

    async def stream_turn(self, *, system_blocks: list[dict], messages: list[dict], model: str) -> AsyncIterator[dict]: ...

    async def list_models(self) -> list[dict]: ...

    async def test_connection(self) -> dict: ...
