from __future__ import annotations

import asyncio
import json

import httpx

SECRET = "sk-live-THIS-MUST-NEVER-APPEAR-9f8e7d6c5b4a"


def run(coro):
    return asyncio.run(coro)


async def collect(agen):
    return [event async for event in agen]


def sse(*events: dict, named: bool = False) -> bytes:
    out = []
    for e in events:
        if named:
            out.append(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n")
        else:
            out.append(f"data: {json.dumps(e)}\n\n")
    return "".join(out).encode()


class Recorder:
    """An httpx.MockTransport handler that records requests and answers from a routing function."""

    def __init__(self, route):
        self.route = route
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            result = self.route(request)
            if isinstance(result, Exception):
                raise result
            return result

        return httpx.MockTransport(handler)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.content]


def json_response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload)


NEUTRAL_HISTORY = [
    {"role": "user", "blocks": [{"type": "text", "text": "How was my sleep?"}]},
    {
        "role": "assistant",
        "blocks": [
            {"type": "text", "text": "Let me check."},
            {"type": "tool_call", "id": "ollama_call_1", "name": "get_today", "input": {}},
        ],
    },
    {"role": "user", "blocks": [{"type": "tool_result", "id": "ollama_call_1", "output": {"recovery": 71}, "is_error": False}]},
    {"role": "assistant", "blocks": [{"type": "text", "text": "Recovery is 71."}]},
    {"role": "user", "blocks": [{"type": "text", "text": "And strain?"}]},
]
