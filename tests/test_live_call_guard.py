from __future__ import annotations

import httpx
import pytest

from conftest import _LiveNetworkCallError


def test_the_live_network_guard_actually_fires():
    """A self-test for tests/conftest.py's `_no_live_network_calls_anywhere` autouse fixture —
    without this, a passing suite would look identical whether the patch works or silently
    does nothing. Targets a real (reserved, RFC 2606) hostname rather than something that
    might resolve, so a future change that narrows the patched surface fails loudly here
    instead of a real request occasionally slipping out undetected."""
    with pytest.raises(_LiveNetworkCallError):
        httpx.Client().get("https://example.invalid/")


def test_mock_transport_is_unaffected():
    """The guard must never interfere with this suite's actual, legitimate use of httpx —
    every fixture-driven client test in this repo uses `httpx.MockTransport`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    resp = client.get("https://example.invalid/")
    assert resp.json() == {"ok": True}
