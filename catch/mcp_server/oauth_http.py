"""Transport-level protection for the OAuth endpoints the SDK serves: a per-source-address throttle (registration is unauthenticated,
and /token and /authorize take attacker-controlled input) and `no-store` on every token response (RFC 6749 §5.1)."""

from __future__ import annotations

import json
import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from catch.coach import limits

logger = logging.getLogger("catch.oauth")
_MAX_LOGGED_BODY = 2048
_BUCKETS = {"/register": "oauth_register", "/token": "oauth_token", "/authorize": "oauth_token", "/revoke": "oauth_token"}


def _log_rejections(path: str, send: Send) -> Send:
    """A rejected /register, /authorize, /token or /revoke is otherwise invisible to the operator (the platform log has the status line,
    not the body), which made a real client's failed registration undiagnosable. Logs only the server-generated RFC 6749/7591 error code and
    description of a 4xx — never the request, never a token (and every log record also passes core/redact.py)."""
    state: dict = {"status": 0, "body": b""}

    async def wrapped(message) -> None:
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
        elif message["type"] == "http.response.body" and state["status"] >= 400 and state["status"] != 429:
            state["body"] += message.get("body", b"")[: _MAX_LOGGED_BODY - len(state["body"])]
            if not message.get("more_body"):
                try:
                    detail = json.loads(state["body"])
                    code, text = detail.get("error"), detail.get("error_description")
                except (ValueError, AttributeError):
                    code, text = None, None
                logger.warning("oauth %s rejected: %s %s: %s", path, state["status"], code, str(text)[:300])
        await send(message)

    return wrapped


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
        await self.app(scope, receive, _log_rejections(scope["path"], send))
