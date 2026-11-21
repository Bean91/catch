"""Request-size limits and image sniffing.

Multipart parsing buffers an upload before a route handler ever runs, so a size check inside the handler (after
`await photo.read()`) is too late to protect memory. The limit is enforced here, on the ASGI stream, and a route's own
validation is then only about *what* the bytes are."""

from __future__ import annotations

import re

from fastapi import HTTPException

MB = 1024 * 1024
DEFAULT_BODY_LIMIT = 2 * MB  # JSON bodies are small; nothing legitimate here is bigger
PHOTO_LIMIT = 6 * MB  # the web client downsizes to ~1500 px first; Storage's own bucket limit is 5 MB
LOGO_LIMIT = 300 * 1024  # 256 KB of image plus slack; the service enforces the exact figure
TOOL_BODY_LIMIT = 64 * 1024

_PHOTO_PATHS = re.compile(r"^/api/(nutrition/photo-estimate|activities/[^/]+/pieces/(photo-estimate|with-photo)|pieces/[^/]+/photo)$")
_LOGO_PATH = re.compile(r"^/api/clubs/[^/]+/logo$")


def body_limit_for(path: str) -> int:
    if _PHOTO_PATHS.match(path):
        return PHOTO_LIMIT
    if _LOGO_PATH.match(path):
        return LOGO_LIMIT
    if path.startswith("/api/coach/tools/"):
        return TOOL_BODY_LIMIT
    return DEFAULT_BODY_LIMIT


def _too_large() -> HTTPException:
    # An HTTPException, not a private type: FastAPI turns any *other* exception raised while it reads a body into a 400.
    return HTTPException(status_code=413, detail="That request is too large.")


class BodyLimitMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware, which would buffer): rejects on Content-Length up front, and counts bytes
    as they stream in for chunked bodies that declare none."""

    def __init__(self, app, limit_for=body_limit_for):
        self.app = app
        self.limit_for = limit_for

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length")

        async def reject():
            body = b'{"detail":"That request is too large."}'
            await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

        if declared is not None and declared.isdigit() and int(declared) > limit:
            await reject()
            return
        received = 0

        async def counted_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _too_large()
            return message

        await self.app(scope, counted_receive, send)


def sniff_image(data: bytes) -> str | None:
    """The content type the bytes really are (jpeg/png/webp), or None. Never trust the client's declared type."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
