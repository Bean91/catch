from dataclasses import replace

from mcp.server.transport_security import TransportSecurityMiddleware

from catch.mcp_server import http_app


def _validator(monkeypatch, base_url):
    monkeypatch.setattr(http_app, "settings", replace(http_app.settings, base_url=base_url))
    return TransportSecurityMiddleware(http_app._transport_security())


def test_public_base_url_host_is_allowed(monkeypatch):
    v = _validator(monkeypatch, "https://catch.example.com")
    assert v._validate_host("catch.example.com")
    assert v._validate_origin("https://catch.example.com")


def test_loopback_with_any_port_and_foreign_hosts(monkeypatch):
    v = _validator(monkeypatch, "https://catch.example.com")
    assert v._validate_host("127.0.0.1:8000")
    assert v._validate_host("localhost:8731")
    assert not v._validate_host("evil.example.org")
    assert not v._validate_origin("https://evil.example.org")


def _stateless_flags(deployment: str) -> str:
    import subprocess
    import sys
    from pathlib import Path

    code = "import catch.mcp_server.http_app as h; m = h.mcp_server.session_manager; print(m.stateless, m.json_response)"
    root = Path(__file__).resolve().parents[1]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "PYTHONPATH": str(root), "CATCH_DEPLOYMENT": deployment,
           "SUPABASE_URL": "https://x.supabase.co", "DATABASE_URL": "postgresql://u:p@127.0.0.1:1/db"}
    out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-600:]
    return out.stdout.strip().splitlines()[-1]


def test_public_mcp_is_stateless_json_and_the_pi_keeps_sdk_defaults():
    # Scale-to-zero + several replicas: an in-memory Mcp-Session-Id would be unknown to the next request.
    assert _stateless_flags("public") == "True True"
    assert _stateless_flags("personal") == "False False"


def test_a_rejected_oauth_request_logs_the_servers_error_description(caplog):
    import asyncio
    import logging

    from starlette.responses import JSONResponse

    from catch.mcp_server.oauth_http import OAuthThrottleMiddleware

    async def app(scope, receive, send):
        await JSONResponse({"error": "invalid_client_metadata", "error_description": "Requested scopes are not valid: profile"}, status_code=400)(scope, receive, send)

    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    scope = {"type": "http", "path": "/register", "client": ("203.0.113.9", 1), "headers": []}
    with caplog.at_level(logging.WARNING, logger="catch.oauth"):
        asyncio.run(OAuthThrottleMiddleware(app)(scope, receive, send))
    assert sent[0]["status"] == 400  # the response itself is untouched
    assert any("invalid_client_metadata" in r.getMessage() and "profile" in r.getMessage() for r in caplog.records)
