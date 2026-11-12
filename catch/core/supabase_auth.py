"""Session 24 (docs/public-architecture.md §4, §6): verifying a Supabase Auth access token.

Verified locally against the project's JWKS — signature (ES256/RS256 only; never HS256 or `none`), issuer,
audience, expiry — and then against the one thing a signature cannot tell us: whether the session was signed out
or its user deleted (an access token stays cryptographically valid until `exp`; Supabase's documented check is that
`session_id` still names a row in `auth.sessions`). The user id is the verified `sub`, nothing else.

PyJWT/cryptography are imported lazily: the Pi never installs the public extra."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from catch.core import config

ALLOWED_ALGORITHMS = ("ES256", "RS256")
JWKS_TTL_SECONDS = 300  # Supabase's edge caches the JWKS for 10 minutes; never hold it longer than that
JWKS_MIN_REFETCH_SECONDS = 10  # an unknown `kid` triggers one refetch, not one per request
LEEWAY_SECONDS = 5


class AuthError(Exception):
    def __init__(self, detail: str, status_code: int = 401):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class Claims:
    sub: str
    session_id: str
    email: Optional[str]
    aal: Optional[str]
    exp: int


def issuer() -> str:
    return f"{config.settings.supabase_url}/auth/v1"


def jwks_url() -> str:
    return f"{issuer()}/.well-known/jwks.json"


def _http_fetch_jwks() -> dict:
    import httpx

    resp = httpx.get(jwks_url(), timeout=5.0, headers={"accept": "application/json"})
    resp.raise_for_status()
    return resp.json()


class JwksCache:
    def __init__(self, fetch: Callable[[], dict] | None = None, clock: Callable[[], float] = time.monotonic):
        self._fetch = fetch or _http_fetch_jwks
        self._clock = clock
        self._lock = threading.Lock()
        self._keys: dict[str, dict] = {}
        self._fetched_at: float | None = None

    def reset(self) -> None:
        with self._lock:
            self._keys, self._fetched_at = {}, None

    def _refresh(self) -> None:
        data = self._fetch()
        self._keys = {k["kid"]: k for k in data.get("keys", []) if k.get("kid")}
        self._fetched_at = self._clock()

    def jwk(self, kid: str) -> dict:
        with self._lock:
            now = self._clock()
            stale = self._fetched_at is None or now - self._fetched_at > JWKS_TTL_SECONDS
            if stale:
                self._refresh()
            elif kid not in self._keys and now - (self._fetched_at or 0) >= JWKS_MIN_REFETCH_SECONDS:
                self._refresh()  # a freshly rotated-in key
            if kid not in self._keys:
                raise AuthError("Unknown signing key")
            return self._keys[kid]


jwks_cache = JwksCache()


def _uuid(value: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise AuthError(f"Invalid {what} claim") from None


def verify_access_token(token: str) -> Claims:
    import jwt
    from jwt import PyJWK

    if not config.settings.supabase_url:
        raise AuthError("Authentication is not configured", 503)
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise AuthError("Invalid token") from None
    alg, kid = header.get("alg"), header.get("kid")
    if alg not in ALLOWED_ALGORITHMS or not kid:
        raise AuthError("Unsupported token")
    try:
        key = PyJWK.from_dict(jwks_cache.jwk(kid), algorithm=alg).key
        payload = jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience=config.settings.supabase_jwt_audience,
            issuer=issuer(),
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except AuthError:
        raise
    except jwt.ExpiredSignatureError:
        raise AuthError("Token expired") from None
    except jwt.PyJWTError:
        raise AuthError("Invalid token") from None
    except Exception:  # noqa: BLE001 — a JWKS fetch failure must not look like a bad token to the caller
        raise AuthError("Authentication is temporarily unavailable", 503) from None
    if payload.get("role") != "authenticated" or payload.get("is_anonymous") is True:
        raise AuthError("Token is not a signed-in user's")
    return Claims(
        sub=_uuid(payload["sub"], "sub"),
        session_id=_uuid(payload.get("session_id"), "session_id"),
        email=payload.get("email"),
        aal=payload.get("aal"),
        exp=int(payload["exp"]),
    )


# --- revocation ---------------------------------------------------------------------------------------------------


class SessionLiveness:
    """Caches 'this session still exists' for a few seconds so revocation is bounded by
    CATCH_SESSION_CHECK_TTL (default 15 s) rather than costing a query on every request. A dead session is
    remembered permanently — session ids are never reused."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_entries: int = 4096):
        self._clock = clock
        self._max = max_entries
        self._lock = threading.Lock()
        self._alive: dict[str, float] = {}
        self._dead: set[str] = set()

    def reset(self) -> None:
        with self._lock:
            self._alive.clear()
            self._dead.clear()

    def check(self, session_id: str, query: Callable[[str], bool]) -> bool:
        ttl = config.settings.supabase_session_check_ttl
        now = self._clock()
        with self._lock:
            if session_id in self._dead:
                return False
            seen = self._alive.get(session_id)
            if seen is not None and now - seen < ttl:
                return True
        live = query(session_id)
        with self._lock:
            if not live:
                self._dead.add(session_id)
                self._alive.pop(session_id, None)
                if len(self._dead) > self._max:
                    self._dead.pop()
            else:
                if len(self._alive) > self._max:
                    self._alive.clear()
                self._alive[session_id] = now
        return live


liveness = SessionLiveness()


def session_is_live(session_id: str) -> bool:
    from sqlalchemy import text
    from sqlmodel import Session

    from catch.core import db, tenant, tenant_hooks

    def query(sid: str) -> bool:
        with tenant.system(), Session(db.engine) as s:
            if tenant_hooks.uses_rls(db.engine):
                return bool(s.connection().execute(text("SELECT catch_private.session_is_live(:sid)"), {"sid": sid}).scalar())
            return True  # no auth.sessions outside the Supabase runtime; unit tests of the public path replace this

    return liveness.check(session_id, query)


def authenticate_bearer(token: str) -> Claims:
    claims = verify_access_token(token)
    if not session_is_live(claims.session_id):
        raise AuthError("Session has ended")
    return claims
