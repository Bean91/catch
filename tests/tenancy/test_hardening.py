"""Session 28 response hardening: no value echoed in a 422, nothing under /api cacheable, no public API docs."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from catch.api.security_headers import SecurityHeadersMiddleware, build_csp
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

ROOT = Path(__file__).resolve().parents[2]
SECRET = "sk-ant-api03-ZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
A = bearer(kit.ALICE)


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("PUT", "/api/connections/garmin/credential", {"apikey": SECRET}),  # misspelt field: the old handler echoed the whole body
        ("PUT", "/api/connections/garmin/credential", {"api_key": {"nested": SECRET}}),
        ("POST", "/api/push/subscribe", {"endpoint": SECRET}),
        ("POST", "/api/notes", {"text": {"x": SECRET}}),
        ("PUT", "/api/ai/providers/anthropic/key", {"api_key": 12345, "extra": SECRET}),
    ],
)
def test_a_422_never_hands_the_submitted_value_back(pub_client, method, path, body):
    pub_client.get("/api/me", headers=A)
    resp = pub_client.request(method, path, headers=A, json=body)
    assert resp.status_code == 422, resp.text
    assert SECRET not in resp.text and "ZZZZZZZZ" not in resp.text
    assert all(set(e) <= {"type", "loc", "msg"} for e in resp.json()["detail"])


def _run(path: str):
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def go():
        mw = SecurityHeadersMiddleware(app, build_csp(""))

        async def send(m):
            sent.append(m)

        await mw({"type": "http", "path": path}, None, send)

    asyncio.run(go())
    return dict(sent[0]["headers"])


@pytest.mark.parametrize("path", ["/api/wellness", "/api/coach/tokens", "/oauth/token", "/auth/whoop/callback", "/internal/tick/sync", "/mcp/"])
def test_dynamic_responses_are_never_stored_by_a_browser_or_proxy(path):
    headers = _run(path)
    assert headers[b"cache-control"] == b"no-store"


def test_static_assets_keep_their_own_caching():
    assert b"cache-control" not in _run("/assets/index-abc123.js")


def test_cross_origin_isolation_headers_are_set():
    headers = _run("/")
    assert headers[b"cross-origin-opener-policy"] == b"same-origin" and headers[b"cross-origin-resource-policy"] == b"same-origin"


def test_a_public_deployment_publishes_no_api_docs():
    code = "import catch.main as m; print(m.app.docs_url, m.app.redoc_url, m.app.openapi_url)"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(ROOT), "CATCH_DEPLOYMENT": "public", "SUPABASE_URL": "https://x.supabase.co", "DATABASE_URL": "postgresql://u:p@127.0.0.1:1/db", "PYTHONPATH": str(ROOT)}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-600:]
    assert out.stdout.strip() == "None None None"
