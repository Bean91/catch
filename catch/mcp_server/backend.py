from __future__ import annotations

from typing import Protocol

from contextvars import ContextVar

import httpx

from catch.core.principal import Principal

current_principal: ContextVar[Principal | None] = ContextVar("catch_mcp_principal", default=None)


class ToolBackend(Protocol):
    async def call_tool(self, name: str, args: dict) -> dict: ...


class RestBackend:
    """Thin REST client over Catch's shared tool endpoint (`POST /api/coach/tools/{name}`),
    authenticated with a per-device bearer token — the stdio transport uses this so Claude
    Desktop can run on a laptop while Catch itself runs on the Pi."""

    def __init__(self, base_url: str, token: str):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers={"Authorization": f"Bearer {token}", "X-Catch-Client": "mcp"}, timeout=30.0
        )

    async def call_tool(self, name: str, args: dict) -> dict:
        resp = await self._client.post(f"/api/coach/tools/{name}", json={"args": args})
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()


class InProcessBackend:
    """Used only by the `/mcp` mount running inside Catch's own single-worker uvicorn process
    — a synchronous (or even async, same-event-loop) HTTP call back to that same worker can
    deadlock waiting on itself, so this dispatches straight into the shared tool registry
    instead of round-tripping through HTTP."""

    async def call_tool(self, name: str, args: dict) -> dict:
        from catch.coach import tools as tools_module
        from catch.core.db import get_session
        from catch.core.principal import VIEWER, may_call_tool

        # Set per request by http_app's bearer middleware. Unset (a bug, or a call that bypassed
        # the middleware) means the fail-closed viewer, which may call nothing.
        principal = current_principal.get() or VIEWER
        if not may_call_tool(principal, name):
            raise PermissionError(f"This token's role can't use '{name}'")
        with get_session() as session:
            return tools_module.call_tool(session, name, args, ctx={"principal": principal, "via": "mcp"})
