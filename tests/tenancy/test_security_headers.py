from __future__ import annotations

from pathlib import Path

import pytest

from catch.api.security_headers import SecurityHeadersMiddleware, build_csp, inline_script_hashes

ROOT = Path(__file__).resolve().parents[2]


def test_the_policy_allows_only_self_and_the_auth_project():
    csp = build_csp("https://abc.supabase.co")
    assert "default-src 'self'" in csp and "connect-src 'self' https://abc.supabase.co" in csp
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "script-src 'self' 'wasm-unsafe-eval'" in csp and "script-src 'unsafe-inline'" not in csp and "unsafe-eval'" not in csp.replace("wasm-unsafe-eval", "")


def test_the_inline_theme_script_is_allowed_by_hash_not_by_unsafe_inline():
    html = '<head><script>var a = 1;</script><script type="module" src="/x.js"></script></head>'
    hashes = inline_script_hashes(html)
    assert len(hashes) == 1 and hashes[0].startswith("'sha256-")
    assert hashes[0] in build_csp("", html)


@pytest.mark.skipif(not (ROOT / "catch/api/static/index.html").is_file(), reason="frontend not built")
def test_the_built_index_needs_nothing_the_policy_forbids():
    html = (ROOT / "catch/api/static/index.html").read_text()
    assert len(inline_script_hashes(html)) <= 1  # only the theme guard
    assert " onclick=" not in html and "javascript:" not in html and "<style" not in html.lower()


def test_headers_are_added_without_overriding_the_apps_own():
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"x-frame-options", b"SAMEORIGIN")]})
        await send({"type": "http.response.body", "body": b"ok"})

    import asyncio

    async def run():
        mw = SecurityHeadersMiddleware(app, "default-src 'self'")
        await mw({"type": "http"}, None, lambda m: _collect(sent, m))

    async def _collect(buf, m):
        buf.append(m)

    asyncio.run(run())
    headers = dict(sent[0]["headers"])
    assert headers[b"content-security-policy"] == b"default-src 'self'" and headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-frame-options"] == b"SAMEORIGIN"  # not duplicated or overridden
