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
