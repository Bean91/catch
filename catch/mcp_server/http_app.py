from __future__ import annotations

from sqlmodel import select
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from catch.api.deps import hash_token
from catch.core.db import get_session
from catch.core.models import ApiToken
from catch.mcp_server.backend import InProcessBackend
from catch.mcp_server.server import build_server

# Module-level singleton: streamable_http_app() lazily creates the session manager
# (verified against the installed mcp SDK — it errors if accessed before this call), so it
# must be built exactly once and shared between the lifespan hook and the mount below.
mcp_server = build_server(InProcessBackend())
_mcp_asgi_app = mcp_server.streamable_http_app(streamable_http_path="/")


class _BearerAuthMiddleware:
    """Wraps the mounted /mcp app with Catch's own device-token check. The MCP SDK's built-in
    auth machinery is for acting as a full OAuth resource server, which is more than this
    single-user, Tailscale-only endpoint needs — a flat bearer-token check matches how the
    stdio transport and the shared tool REST endpoint already authenticate."""

    def __init__(self, app: ASGIApp):
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"").decode()
        token = auth_header[len("bearer ") :].strip() if auth_header.lower().startswith("bearer ") else ""
        if not token or not self._token_is_valid(token):
            response = JSONResponse({"detail": "Not authenticated"}, status_code=401)
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)

    @staticmethod
    def _token_is_valid(raw_token: str) -> bool:
        with get_session() as session:
            row = session.exec(select(ApiToken).where(ApiToken.token_hash == hash_token(raw_token))).first()
            return row is not None


def mounted_mcp_app() -> ASGIApp:
    return _BearerAuthMiddleware(_mcp_asgi_app)
