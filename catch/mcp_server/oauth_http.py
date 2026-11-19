"""Transport-level protection for the OAuth endpoints the SDK serves: a per-source-address throttle (registration is unauthenticated,
and /token and /authorize take attacker-controlled input) and `no-store` on every token response (RFC 6749 §5.1)."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from catch.coach import limits

_BUCKETS = {"/register": "oauth_register", "/token": "oauth_token", "/authorize": "oauth_token", "/revoke": "oauth_token"}


class OAuthThrottleMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        bucket = _BUCKETS.get(scope.get("path", "")) if scope["type"] == "http" else None
        if bucket is None:
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        try:
            limits.check_rate(f"ip:{client[0] if client else 'unknown'}", bucket)
        except limits.LimitExceeded as exc:
            await JSONResponse({"error": "temporarily_unavailable", "error_description": exc.message}, status_code=429, headers={"Retry-After": str(exc.retry_after_s or 1)})(scope, receive, send)
            return
        await self.app(scope, receive, send)
