from __future__ import annotations

import asyncio

import pytest

from catch.api.sse import stream_until_disconnected


async def _collect(agen):
    return [x async for x in agen]


async def _never_disconnected():
    return False


def test_yields_every_item_when_never_disconnected():
    async def source():
        for i in range(3):
            yield i

    result = asyncio.run(_collect(stream_until_disconnected(source(), _never_disconnected)))
    assert result == [0, 1, 2]


def test_stops_and_cancels_on_disconnect_mid_wait():
    closed = False
    cancelled = False

    async def source():
        nonlocal closed, cancelled
        try:
            yield "first"
            # Sleeps far longer than the poll interval — simulates a slow provider call with
            # nothing to yield in between, the exact scenario that silently kept running live.
            await asyncio.sleep(10)
            yield "second"  # pragma: no cover - should never be reached
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            closed = True

    disconnect_after_first = {"seen_first": False}

    async def is_disconnected():
        if disconnect_after_first["seen_first"]:
            return True
        return False

    async def run():
        out = []
        async for item in stream_until_disconnected(source(), is_disconnected, poll_interval=0.05):
            out.append(item)
            disconnect_after_first["seen_first"] = True
        return out

    result = asyncio.run(run())
    assert result == ["first"]
    assert cancelled is True
    assert closed is True


def test_closes_source_even_when_exhausted_normally():
    closed = False

    async def source():
        nonlocal closed
        try:
            yield 1
        finally:
            closed = True

    asyncio.run(_collect(stream_until_disconnected(source(), _never_disconnected)))
    assert closed is True


def test_propagates_exceptions_from_source():
    async def source():
        yield 1
        raise ValueError("boom")

    async def run():
        return await _collect(stream_until_disconnected(source(), _never_disconnected))

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(run())
