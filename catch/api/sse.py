from __future__ import annotations

import asyncio
from typing import AsyncIterator, Awaitable, Callable, TypeVar

T = TypeVar("T")

_DISCONNECT_POLL_INTERVAL_S = 1.0


async def stream_until_disconnected(
    source: AsyncIterator[T],
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_interval: float = _DISCONNECT_POLL_INTERVAL_S,
) -> AsyncIterator[T]:
    """Advances `source`, polling `is_disconnected` every `poll_interval` seconds while
    waiting for its next item — not just once per item. A closed SSE client otherwise has no
    effect on a source that's mid-await on a slow network call (confirmed live: a coach turn
    against a "thinking" Ollama model kept running, and got persisted, long after the curl
    client that started it was killed). On disconnect, the pending `__anext__()` call is
    cancelled, which throws into whatever `source` is awaiting (the provider's HTTP stream
    read) the same way any cancelled `await` does — including running any `async with`/
    `finally` cleanup inside `source` — so the underlying connection still closes cleanly.

    Deliberately does NOT also call `source.aclose()` after that: calling it on a generator
    whose own `__anext__()` call is being unwound by that same cancellation raises
    `RuntimeError: aclose(): asynchronous generator is already running` (hit live — the first
    version of this function called aclose() unconditionally in a `finally` block). Only call
    aclose() when `source` is genuinely idle between calls, which `__anext__()` reaching
    StopAsyncIteration already guarantees on its own — there's nothing left to close there
    either.
    """
    while True:
        next_item = asyncio.ensure_future(source.__anext__())
        while True:
            done, _ = await asyncio.wait({next_item}, timeout=poll_interval)
            if next_item in done:
                break
            if await is_disconnected():
                next_item.cancel()
                try:
                    await next_item
                except (asyncio.CancelledError, StopAsyncIteration):
                    pass
                except Exception:
                    # Whatever source was doing when cancelled (e.g. an HTTP client's own
                    # teardown) may itself raise during unwind — the turn is being abandoned
                    # either way, so there's nothing useful to do with that exception here.
                    pass
                return
        try:
            yield next_item.result()
        except StopAsyncIteration:
            return
