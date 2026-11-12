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
