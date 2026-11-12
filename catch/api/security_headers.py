"""Session 24 (docs/public-architecture.md, web/src/lib/supabase.ts): response headers for the public deployment.

The browser keeps its Supabase session in localStorage (an SPA with a separate API has no httpOnly option), so the real
defence for that token is not letting foreign script run at all: a strict Content-Security-Policy. The one inline script
in index.html (the theme flash-guard) is allowed by hash, computed from the built file, not by 'unsafe-inline'."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def inline_script_hashes(index_html: str) -> list[str]:
    out = []
    for body in _INLINE_SCRIPT.findall(index_html):
        digest = hashlib.sha256(body.encode()).digest()
        out.append(f"'sha256-{base64.b64encode(digest).decode()}'")
    return out


def build_csp(supabase_url: str, index_html: str = "") -> str:
    connect = ["'self'"] + ([supabase_url] if supabase_url else [])
    script = ["'self'", "'wasm-unsafe-eval'", *inline_script_hashes(index_html)]  # wasm: the self-hosted barcode decoder
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src {' '.join(script)}",
            "style-src 'self' 'unsafe-inline'",  # style *attributes* only; scripts stay locked down
            "img-src 'self' data: blob: https://tile.openstreetmap.org https://*.tile.openstreetmap.org",
            "font-src 'self' data:",
            f"connect-src {' '.join(connect)}",
            "worker-src 'self' blob:",
            "manifest-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


class SecurityHeadersMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware): it must not buffer or re-task the coach's SSE responses."""

    def __init__(self, app: ASGIApp, csp: str):
        self.app = app
        self.headers = [
            (b"content-security-policy", csp.encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"camera=(self), geolocation=(), microphone=()"),
            (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
            (b"x-frame-options", b"DENY"),
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [(k, v) for k, v in self.headers if k not in present]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def csp_for_static(static_dir: Path, supabase_url: str) -> str:
    index = static_dir / "index.html"
    return build_csp(supabase_url, index.read_text() if index.is_file() else "")
