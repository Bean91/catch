from __future__ import annotations

from urllib.parse import urlsplit

from mcp.server.transport_security import TransportSecuritySettings
from sqlmodel import select
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from catch.api.deps import hash_token
from catch.core.config import settings
from catch.core.db import get_session
from catch.core.models import ApiToken
from catch.core.principal import Principal, principal_from_token
from catch.mcp_server.backend import InProcessBackend, current_principal
from catch.mcp_server.server import build_server

# Module-level singleton: streamable_http_app() lazily creates the session manager
# (verified against the installed mcp SDK — it errors if accessed before this call), so it
# must be built exactly once and shared between the lifespan hook and the mount below.
mcp_server = build_server(InProcessBackend())


def _transport_security() -> TransportSecuritySettings:
    # The SDK only allows loopback Host headers by default and answers anything else with
    # "421 Invalid Host header" — which is what a request arriving via the public hostname
    # (Cloudflare tunnel / tailscale serve) looks like. The bearer check below is the real gate;
    # this keeps DNS-rebinding protection on for every host except the configured base URL's.
    host = urlsplit(settings.base_url).netloc
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    if host:
        hosts.append(host)
        origins += [f"https://{host}", f"http://{host}"]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


_mcp_asgi_app = mcp_server.streamable_http_app(streamable_http_path="/", transport_security=_transport_security())


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
        principal = self._principal_for(token) if token else None
        if principal is None:
            response = JSONResponse({"detail": "Not authenticated"}, status_code=401)
            await response(scope, receive, send)
            return
        # Scoped to this request; reset in `finally` so a later request can never inherit it.
        reset = current_principal.set(principal)
        try:
            await self._app(scope, receive, send)
        finally:
            current_principal.reset(reset)

    @staticmethod
    def _principal_for(raw_token: str) -> Principal | None:
        with get_session() as session:
            row = session.exec(select(ApiToken).where(ApiToken.token_hash == hash_token(raw_token))).first()
            return principal_from_token(row.id, row.role, row.display_name) if row is not None else None


def mounted_mcp_app() -> ASGIApp:
    return _BearerAuthMiddleware(_mcp_asgi_app)
