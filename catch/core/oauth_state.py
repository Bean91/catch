"""Who is this OAuth callback for? (session 25; docs/provider-connections.md)

A provider redirects the *browser* back to Catch, and a browser redirect carries no Authorization header — so on the public
deployment the callback can't be authenticated the usual way. Instead the bearer-authenticated "start" call sets a short-lived
signed cookie naming the owner and a random nonce, and the URL `state` carries only that nonce (Whoop insists `state` is exactly
eight characters, so nothing else fits there). The callback accepts a code only when the cookie's signature and expiry are valid and
its nonce equals the URL's `state`: a code can't be attached to another account by forging a link, and replaying a stale link fails.

Assumption (docs/provider-connections.md): the page and the API share an origin, so the cookie reaches the callback."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from catch.core import secret_store
from catch.core.config import settings

TTL_SECONDS = 600


class OAuthStateError(ValueError):
    """Fixed text only; never the cookie, the state or a code."""


def cookie_name(provider: str) -> str:
    return f"catch_oauth_{provider}"


def new_nonce(provider: str) -> str:
    # Whoop: "must be eight characters long" — 6 random bytes encode to exactly 8 URL-safe characters.
    return secrets.token_urlsafe(6 if provider == "whoop" else 18)


def _keys() -> list[bytes]:
    return [
        HKDF(algorithm=hashes.SHA256(), length=32, salt=b"catch-oauth-state", info=b"catch/oauth-state/v1").derive(raw)
        for _, raw in secret_store._masters()
    ]


def _sign(key: bytes, body: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(key, body.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def make(owner: str, provider: str, nonce: str, *, now: float | None = None, native: bool = False) -> str:
    keys = _keys()
    if not keys:
        raise OAuthStateError("The server has no secrets master key configured.")
    payload = {"o": owner, "p": provider, "n": nonce, "e": int((now if now is not None else time.time()) + TTL_SECONDS)}
    if native:
        payload["x"] = 1  # the flow ends in the store app (custom-scheme return), not a page
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{body}.{_sign(keys[0], body)}"


def verify(cookie: str | None, provider: str, state: str | None, *, now: float | None = None) -> str:
    """Returns the owner the flow was started for, or raises OAuthStateError."""
    return verify_full(cookie, provider, state, now=now)[0]


def verify_full(cookie: str | None, provider: str, state: str | None, *, now: float | None = None) -> tuple[str, bool]:
    """(owner, started_from_the_native_app)."""
    if not cookie or not state or "." not in cookie:
        raise OAuthStateError("Invalid or missing OAuth state.")
    body, signature = cookie.rsplit(".", 1)
    # compare_digest raises TypeError on non-ASCII `str`s; encode so a crafted cookie is a clean refusal, never a 500.
    if not any(hmac.compare_digest(_sign(key, body).encode(), signature.encode("utf-8", "replace")) for key in _keys()):
        raise OAuthStateError("Invalid or missing OAuth state.")
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        owner, prov, nonce, exp = payload["o"], payload["p"], payload["n"], int(payload["e"])
    except (ValueError, KeyError, TypeError):
        raise OAuthStateError("Invalid or missing OAuth state.") from None
    if prov != provider or exp < (now if now is not None else time.time()) or not secrets.compare_digest(str(nonce).encode(), state.encode("utf-8", "replace")):
        raise OAuthStateError("Invalid or missing OAuth state.")
    _consume(str(nonce), exp, now if now is not None else time.time())
    return owner, bool(payload.get("x"))


# ---- native start tickets (session 30, docs/mobile/oauth-return.md) ----
# The store app can't set a cookie in the system browser where the provider's sign-in page runs, and the browser it opens has no
# bearer token. So the bearer-authenticated start call returns a ticket instead: a short-lived, single-use, signed claim "this
# owner may begin <provider> authorisation". Opening GET /auth/{provider}/native-start?ticket= in the system browser redeems it
# there, which is where the state cookie is then set. The ticket is useless for anything else (different key derivation, 2-minute
# lifetime, redeemed once) and names no credential.

TICKET_TTL_SECONDS = 120


def _ticket_keys() -> list[bytes]:
    return [
        HKDF(algorithm=hashes.SHA256(), length=32, salt=b"catch-oauth-state", info=b"catch/oauth-native-ticket/v1").derive(raw)
        for _, raw in secret_store._masters()
    ]


def make_ticket(owner: str, provider: str, nonce: str, *, now: float | None = None) -> str:
    keys = _ticket_keys()
    if not keys:
        raise OAuthStateError("The server has no secrets master key configured.")
    payload = {"o": owner, "p": provider, "n": nonce, "e": int((now if now is not None else time.time()) + TICKET_TTL_SECONDS)}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{body}.{_sign(keys[0], body)}"


def redeem_ticket(ticket: str | None, provider: str, *, now: float | None = None) -> tuple[str, str]:
    """(owner, nonce) for a valid, unexpired, never-before-redeemed ticket for this provider."""
    if not ticket or "." not in ticket:
        raise OAuthStateError("Invalid or expired sign-in link.")
    body, signature = ticket.rsplit(".", 1)
    if not any(hmac.compare_digest(_sign(key, body).encode(), signature.encode("utf-8", "replace")) for key in _ticket_keys()):
        raise OAuthStateError("Invalid or expired sign-in link.")
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        owner, prov, nonce, exp = payload["o"], payload["p"], payload["n"], int(payload["e"])
    except (ValueError, KeyError, TypeError):
        raise OAuthStateError("Invalid or expired sign-in link.") from None
    t = now if now is not None else time.time()
    if prov != provider or exp < t:
        raise OAuthStateError("Invalid or expired sign-in link.")
    _consume("ticket:" + str(nonce), exp, t)
    return owner, str(nonce)


_consumed: dict[str, int] = {}
_consumed_lock = threading.Lock()


def _consume(nonce: str, exp: int, now: float) -> None:
    """A state cookie works once. Per replica (a flow starts and finishes on one browser within ten minutes, so it normally
    lands on the replica that issued it), bounded and self-pruning."""
    with _consumed_lock:
        for key in [k for k, e in _consumed.items() if e < now]:
            del _consumed[key]
        if nonce in _consumed:
            raise OAuthStateError("Invalid or missing OAuth state.")
        if len(_consumed) > 5000:
            _consumed.clear()
        _consumed[nonce] = exp


def cookie_kwargs() -> dict:
    return {"httponly": True, "samesite": "lax", "max_age": TTL_SECONDS, "secure": settings.base_url.startswith("https://") or settings.deployment == "public", "path": "/"}
