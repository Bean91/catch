from __future__ import annotations

import logging

import httpx

from catch.core import redact


def test_known_key_shapes_are_removed():
    for secret in ["sk-ant-api03-abcdefghijklmnopqrstuv", "sk-proj-abcdefghijklmnopqrstuv", "AIzaSyA1234567890abcdefghijklmnop"]:
        assert secret not in redact.redact(f"upstream said: invalid key {secret} for request")


def test_query_string_and_bearer_credentials_are_removed():
    out = redact.redact("GET https://x.test/v1?api_key=SUPERSECRETVALUE&page=2 with Bearer abcdefgh12345678")
    assert "SUPERSECRETVALUE" not in out
    assert "abcdefgh12345678" not in out
    assert "page=2" in out


def test_header_style_credentials_are_removed():
    out = redact.redact("{'x-goog-api-key': 'ZZZZZZZZZZZZ', 'x-api-key': 'YYYYYYYYYYYY'}")
    assert "ZZZZ" not in out and "YYYY" not in out


def test_url_userinfo_is_removed():
    assert "hunter2" not in redact.redact("connect failed: http://bob:hunter2@laptop.local:11434/api/chat")


def test_registered_secret_with_an_unfamiliar_shape_is_removed():
    redact.register_secret("weird-format-secret-value")
    try:
        assert "weird-format-secret-value" not in redact.redact("oops weird-format-secret-value leaked")
    finally:
        redact.forget_secret("weird-format-secret-value")


def test_httpx_status_error_text_is_scrubbed():
    request = httpx.Request("GET", "https://api.example.test/search?api_key=LEAKME123456&q=oats")
    exc = httpx.HTTPStatusError("boom", request=request, response=httpx.Response(500, request=request))
    assert "LEAKME123456" not in redact.redact(f"{exc} {request.url}")


def test_log_records_including_tracebacks_are_scrubbed(caplog):
    redact.install_log_filter()
    logger = logging.getLogger("catch.test.redact")
    try:
        raise ValueError("failed with Bearer abcdefgh12345678 in url ?key=TOPSECRETKEY")
    except ValueError:
        with caplog.at_level(logging.WARNING, logger="catch.test.redact"):
            logger.warning("request for %s failed", "https://u:pw@h.test/x?api_key=ABCDEFGH12", exc_info=True)
    text = caplog.text + "".join(r.exc_text or "" for r in caplog.records)
    assert "ABCDEFGH12" not in text
    assert "TOPSECRETKEY" not in text
    assert "abcdefgh12345678" not in text
    assert ":pw@" not in text


def test_a_scrubbed_access_log_record_keeps_its_five_arguments():
    """uvicorn's AccessFormatter unpacks (client, method, path, http_version, status); collapsing them into a string broke every
    request whose URL carried an OAuth-style `code=` (found by the first real browser run against the public build)."""
    import logging

    from catch.core.redact import _scrub_record

    rec = logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:1", "GET", "/?code=abc123XYZ789&x=1", "1.1", 200), None)
    _scrub_record(rec)
    assert len(rec.args) == 5 and rec.args[2] == "/?code=[redacted]&x=1"
    assert "abc123XYZ789" not in rec.getMessage()
    plain = logging.LogRecord("c", logging.INFO, "x", 1, "token sk-proj-abcdefghijklmnopqrstu leaked", (), None)
    _scrub_record(plain)
    assert "sk-proj" not in plain.getMessage()
