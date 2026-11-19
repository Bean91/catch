"""MCP OAuth 2.1 for the /mcp mount (session 28; docs/mcp.md "OAuth").

Catch is its own authorization server for its own resource, built on the installed `mcp` SDK's `OAuthAuthorizationServerProvider`
interface (the SDK supplies the RFC 8414 metadata, RFC 7591 registration, authorize/token/revoke endpoints and PKCE verification; this
module supplies storage and consent). Public deployment only, behind CATCH_MCP_OAUTH_ENABLED.

What it guarantees, and where:
* Authorization needs a signed-in person's explicit approval on Catch's own consent page — the SDK's /authorize only redirects there.
* PKCE (S256) is mandatory and checked by the SDK; a code works once, within 60 seconds, for the client it was issued to, to the exact
  redirect URI.
* Tokens are opaque 256-bit values stored only as SHA-256 hashes. Access 1 h; refresh rotates on every use, lives 30 days and ends
  absolutely at 90; presenting an already-rotated refresh token revokes the whole grant (replay detection).
* Scopes are `catch:read` and `catch:write` (write implies read; writes are still preview-then-confirm). Nothing reaches credentials, AI
  keys, account deletion or club/leaderboard writes.
* Each grant is bound to the resource (this /mcp URL); a token for another resource is refused.
* The owner of every token comes from the stored grant, never from request data. The unauthenticated token endpoint finds the owner with
  two narrow read-only SECURITY DEFINER lookups and then works under that owner's own RLS context."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit

from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError, RefreshToken, RegistrationError, TokenError, construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import delete as sa_delete
from sqlalchemy import text
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from catch.core import db as db_module
from catch.core import secret_store, tenant, tenant_hooks
from catch.core.config import settings
from catch.core.models import OAuthAuthCode, OAuthClient, OAuthGrant

SCOPES = ("catch:read", "catch:write")
SCOPE_TEXT = {
    "catch:read": "Read your training data (only the categories you've allowed the AI to see)",
    "catch:write": "Propose changes: add notes, log food, plan sessions… — each one is shown to you first and saved only when you confirm",
}
CODE_TTL_S = 60
ACCESS_TTL_S = 3600
REFRESH_TTL_DAYS = 30
ABSOLUTE_TTL_DAYS = 90
REQUEST_TTL_S = 600
MAX_CLIENTS = 2000
MAX_REDIRECTS = 5
MAX_ACTIVE_GRANTS = 20


def resource_url() -> str:
    return settings.base_url.rstrip("/") + "/mcp"


def issuer_url() -> str:
    return settings.base_url.rstrip("/")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_secret() -> str:
    return secrets.token_urlsafe(32)


# ---- the signed authorization request (carried through the consent page; nothing is stored until the person approves) -------------

def _request_keys() -> list[bytes]:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return [HKDF(algorithm=hashes.SHA256(), length=32, salt=b"catch-oauth-request", info=b"catch/oauth-authz-request/v1").derive(raw) for _, raw in secret_store._masters()]


def sign_request(payload: dict, *, now: Optional[float] = None) -> str:
    keys = _request_keys()
    if not keys:
        raise RuntimeError("no secrets master key")
    body = base64.urlsafe_b64encode(json.dumps({**payload, "exp": int((now or time.time()) + REQUEST_TTL_S)}, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(keys[0], body.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"{body}.{sig}"


def verify_request(token: str, *, now: Optional[float] = None) -> dict:
    try:
        body, sig = token.rsplit(".", 1)
        ok = any(hmac.compare_digest(base64.urlsafe_b64encode(hmac.new(k, body.encode(), hashlib.sha256).digest()).decode().rstrip("=").encode(), sig.encode("utf-8", "replace")) for k in _request_keys())
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))) if ok else None
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict) or payload.get("exp", 0) < (now or time.time()):
        raise ValueError("This authorization request is invalid or has expired. Start again from the app.")
    return payload


# ---- client registration rules ------------------------------------------------------------------------------------------------------

def _valid_redirect(uri: str) -> bool:
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if parts.fragment or parts.username or parts.password or not parts.hostname:
        return False
    if parts.scheme == "https":
        return True
    # Native apps may use a loopback address over http (RFC 8252); nothing else is plain http.
    return parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")


def validate_client(info: OAuthClientInformationFull) -> None:
    uris = [str(u) for u in (info.redirect_uris or [])]
    if not uris or len(uris) > MAX_REDIRECTS or not all(_valid_redirect(u) for u in uris):
        raise RegistrationError("invalid_redirect_uri", "Redirect URIs must be https (or an http loopback address), without fragments, at most 5.")
    if (info.token_endpoint_auth_method or "none") != "none":
        raise RegistrationError("invalid_client_metadata", "Only public clients (token_endpoint_auth_method=none) are accepted; use PKCE.")
    if info.client_name is not None and not (1 <= len(info.client_name.strip()) <= 80):
        raise RegistrationError("invalid_client_metadata", "client_name must be 1–80 characters.")
    if info.scope and any(s not in SCOPES for s in info.scope.split()):
        raise RegistrationError("invalid_client_metadata", f"Unknown scope. Supported: {' '.join(SCOPES)}")


# ---- storage (sync; the provider calls these through the threadpool) ------------------------------------------------------------------

def _owner_for_hash(session: Session, kind: str, h: str) -> tuple | None:
    """Which owner (and grant) a code or token hash belongs to — the one step that runs before an owner is known."""
    with tenant.system():
        if tenant_hooks.uses_rls(session.get_bind()):
            fn = "resolve_oauth_code" if kind == "code" else "resolve_oauth_token"
            row = session.connection().execute(text(f"SELECT * FROM catch_private.{fn}(:h)"), {"h": h}).first()
            session.rollback()
            return tuple(row) if row else None
        if kind == "code":
            row = session.execute(select(OAuthAuthCode.owner_id).where(OAuthAuthCode.code_hash == h).execution_options(tenant_unscoped=True)).first()
            return (row[0],) if row else None
        g = session.execute(
            select(OAuthGrant).where((OAuthGrant.access_hash == h) | (OAuthGrant.refresh_hash == h) | (OAuthGrant.prev_refresh_hash == h)).execution_options(tenant_unscoped=True)
        ).scalars().first()
        if g is None:
            return None
        return (g.owner_id, g.grant_id, "access" if g.access_hash == h else "refresh" if g.refresh_hash == h else "refresh_prev")


def _client_info(session: Session, client_id: str) -> OAuthClientInformationFull | None:
    from catch.sync.leaderboard_store import store

    with store() as s:
        row = s.get(OAuthClient, client_id)
        return OAuthClientInformationFull.model_validate_json(row.client_json) if row else None


def _touch_client(client_id: str) -> None:
    """Mark a registered client as in use, so retention can drop abandoned registrations (an unauthenticated endpoint creates them)."""
    from catch.sync.leaderboard_store import store

    with store() as s:
        row = s.get(OAuthClient, client_id)
        if row is not None:
            row.last_used_at = _now()
            s.commit()


def create_code(session: Session, *, client_id: str, redirect_uri: str, explicit: bool, challenge: str, scopes: list[str], resource: Optional[str]) -> str:
    """Called under the approving person's own context. Returns the raw code (shown once, in the redirect)."""
    if len(session.exec(select(OAuthGrant).where(OAuthGrant.revoked_at.is_(None), OAuthGrant.absolute_expires_at > _now())).all()) >= MAX_ACTIVE_GRANTS:  # type: ignore[union-attr]
        raise ValueError(f"You already have {MAX_ACTIVE_GRANTS} connected apps. End one first.")
    raw = _new_secret()
    session.add(OAuthAuthCode(code_hash=_hash(raw), client_id=client_id, redirect_uri=redirect_uri, redirect_uri_provided_explicitly=explicit, code_challenge=challenge,
                              scopes=" ".join(scopes), resource=resource, expires_at=_now() + timedelta(seconds=CODE_TTL_S)))
    session.commit()
    return raw


def _issue(session: Session, grant: OAuthGrant) -> tuple[str, str]:
    access, refresh = _new_secret(), _new_secret()
    now = _now()
    grant.prev_refresh_hash = grant.refresh_hash if grant.refresh_hash else None
    grant.access_hash, grant.access_expires_at = _hash(access), now + timedelta(seconds=ACCESS_TTL_S)
    grant.refresh_hash = _hash(refresh)
    grant.refresh_expires_at = min(now + timedelta(days=REFRESH_TTL_DAYS), _aware(grant.absolute_expires_at))
    grant.last_used_at = now
    session.add(grant)
    return access, refresh


def _token_response(access: str, refresh: str, scopes: str) -> OAuthToken:
    return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TTL_S, scope=scopes, refresh_token=refresh)


def redeem_code(client_id: str, code: str) -> Optional[AuthorizationCode]:
    with Session(db_module.engine) as s:
        found = _owner_for_hash(s, "code", _hash(code))
    if not found:
        return None
    owner = found[0]
    with tenant.use_owner(owner), Session(db_module.engine) as s:
        row = s.exec(select(OAuthAuthCode).where(OAuthAuthCode.code_hash == _hash(code))).first()
        if row is None or row.client_id != client_id or _aware(row.expires_at) < _now():
            return None
        return AuthorizationCode(
            code=code, scopes=row.scopes.split(), expires_at=_aware(row.expires_at).timestamp(), client_id=row.client_id, code_challenge=row.code_challenge,
            redirect_uri=row.redirect_uri, redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly, resource=row.resource, subject=owner,
        )


def exchange_code(code: AuthorizationCode) -> OAuthToken:
    owner = code.subject or ""
    with tenant.use_owner(owner), Session(db_module.engine) as s:
        row = s.exec(select(OAuthAuthCode).where(OAuthAuthCode.code_hash == _hash(code.code))).first()
        if row is None:  # already used: a code works once
            raise _Fail("invalid_grant", "Authorization code was already used or has expired.")
        # Delete by id and require that THIS statement removed it: two concurrent redemptions of one code must not both win.
        if s.execute(sa_delete(OAuthAuthCode).where(OAuthAuthCode.id == row.id)).rowcount != 1:
            raise _Fail("invalid_grant", "Authorization code was already used or has expired.")
        now = _now()
        grant = OAuthGrant(grant_id=str(uuid.uuid4()), client_id=code.client_id, scopes=" ".join(code.scopes), resource=code.resource, access_hash="", access_expires_at=now,
                           refresh_hash="", refresh_expires_at=now, absolute_expires_at=now + timedelta(days=ABSOLUTE_TTL_DAYS))
        access, refresh = _issue(s, grant)
        grant.prev_refresh_hash = None
        s.commit()
        return _token_response(access, refresh, grant.scopes)


class _Fail(Exception):
    """Raised inside a worker thread and translated by the async provider methods: the SDK's error types are frozen dataclasses, and
    a frozen exception can't be carried across the thread boundary (setting __traceback__ on it fails)."""

    def __init__(self, error: str, description: str):
        super().__init__(error)
        self.error, self.description = error, description


class CatchRefreshToken(RefreshToken):
    grant_id: str = ""
    replayed: bool = False


def load_refresh(client_id: str, token: str) -> Optional[CatchRefreshToken]:
    with Session(db_module.engine) as s:
        found = _owner_for_hash(s, "token", _hash(token))
    if not found or found[2] not in ("refresh", "refresh_prev"):
        return None
    owner, grant_id, kind = found
    with tenant.use_owner(owner), Session(db_module.engine) as s:
        g = s.get(OAuthGrant, tenant.pk(grant_id))
        if g is None or g.client_id != client_id:
            return None
        return CatchRefreshToken(token=token, client_id=g.client_id, scopes=g.scopes.split(), expires_at=int(_aware(g.refresh_expires_at).timestamp()), resource=g.resource,
                                 subject=owner, grant_id=grant_id, replayed=(kind == "refresh_prev"))


def exchange_refresh(token: CatchRefreshToken, scopes: list[str]) -> OAuthToken:
    with tenant.use_owner(token.subject or ""), Session(db_module.engine) as s:
        g = s.get(OAuthGrant, tenant.pk(token.grant_id), with_for_update=True)  # serialise concurrent refreshes of one grant (a no-op on SQLite)
        if g is None or g.revoked_at is not None:
            raise _Fail("invalid_grant", "This authorization has been revoked.")
        if g.refresh_hash != _hash(token.token) and not token.replayed:
            raise _Fail("invalid_grant", "This refresh token was already used.")  # another request rotated it first
        if token.replayed:
            g.revoked_at = _now()  # a rotated-out refresh token came back: someone is replaying a stolen copy, so end the whole grant
            s.add(g)
            s.commit()
            raise _Fail("invalid_grant", "Refresh token reuse detected; the authorization was revoked.")
        now = _now()
        if _aware(g.refresh_expires_at) < now or _aware(g.absolute_expires_at) < now:
            raise _Fail("invalid_grant", "The refresh token has expired.")
        if scopes and not set(scopes) <= set(g.scopes.split()):
            raise _Fail("invalid_scope", "Cannot widen the granted scope.")
        access, refresh = _issue(s, g)
        s.commit()
        return _token_response(access, refresh, " ".join(scopes) if scopes else g.scopes)


def revoke(token: str) -> None:
    with Session(db_module.engine) as s:
        found = _owner_for_hash(s, "token", _hash(token))
    if not found:
        return
    owner, grant_id = found[0], found[1]
    with tenant.use_owner(owner), Session(db_module.engine) as s:
        g = s.get(OAuthGrant, tenant.pk(grant_id))
        if g is not None and g.revoked_at is None:
            g.revoked_at = _now()
            s.add(g)
            s.commit()


def access_principal(raw: str):
    """The Principal behind an OAuth access token on /mcp, or None. Checks revocation, expiry and the resource binding."""
    found = _access_lookup(raw)
    return found[0] if found else None


def _access_lookup(raw: str):
    from catch.core.principal import athlete_for

    with Session(db_module.engine) as s:
        found = _owner_for_hash(s, "token", _hash(raw))
    if not found or found[2] != "access":
        return None
    owner, grant_id = found[0], found[1]
    with tenant.use_owner(owner), Session(db_module.engine) as s:
        g = s.get(OAuthGrant, tenant.pk(grant_id))
        now = _now()
        if g is None or g.revoked_at is not None or _aware(g.access_expires_at) < now or _aware(g.absolute_expires_at) < now:
            return None
        if g.resource is not None and g.resource.rstrip("/") != resource_url():
            return None  # issued for a different resource
        g.last_used_at = now
        s.add(g)
        s.commit()
        import dataclasses

        base = athlete_for(owner)
        return dataclasses.replace(base, scope="write" if "catch:write" in g.scopes.split() else "read"), g.client_id


def list_grants(session: Session) -> list[dict]:
    now = _now()
    out = []
    for g in session.exec(select(OAuthGrant).order_by(OAuthGrant.created_at.desc())).all():  # type: ignore[attr-defined]
        if g.revoked_at is not None or _aware(g.absolute_expires_at) < now:
            continue
        info = _client_info(session, g.client_id)
        out.append({"grant_id": g.grant_id, "client_name": (info.client_name if info and info.client_name else "An app"), "scopes": g.scopes.split(),
                    "created_at": _aware(g.created_at).isoformat(), "last_used_at": _aware(g.last_used_at).isoformat() if g.last_used_at else None,
                    "expires_at": _aware(g.absolute_expires_at).isoformat()})
    return out


def revoke_grant(session: Session, grant_id: str) -> bool:
    g = session.get(OAuthGrant, tenant.pk(grant_id))
    if g is None or g.revoked_at is not None:
        return False
    g.revoked_at = _now()
    session.add(g)
    session.commit()
    return True


def revoke_all(session: Session) -> int:
    n = 0
    for g in session.exec(select(OAuthGrant).where(OAuthGrant.revoked_at.is_(None))).all():  # type: ignore[union-attr]
        g.revoked_at = _now()
        session.add(g)
        n += 1
    session.commit()
    return n


# ---- the SDK provider --------------------------------------------------------------------------------------------------------------

class CatchOAuthProvider:
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return await run_in_threadpool(lambda: _client_info(None, client_id))  # type: ignore[arg-type]

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        validate_client(client_info)

        def save() -> None:
            from sqlalchemy import func

            from catch.sync.leaderboard_store import store

            with store() as s:
                if s.exec(select(func.count()).select_from(OAuthClient)).one() >= MAX_CLIENTS:
                    raise _Fail("invalid_client_metadata", "Too many registered clients; try again later.")
                s.add(OAuthClient(client_id=client_info.client_id or "", client_json=client_info.model_dump_json(exclude={"client_secret"})))
                s.commit()

        try:
            await run_in_threadpool(save)
        except _Fail as exc:
            raise RegistrationError(exc.error, exc.description) from None  # type: ignore[arg-type]

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        await run_in_threadpool(_touch_client, client.client_id or "")
        scopes = params.scopes or ["catch:read"]
        if any(s not in SCOPES for s in scopes):
            raise AuthorizeError("invalid_scope", f"Supported scopes: {' '.join(SCOPES)}")
        if params.resource is not None and params.resource.rstrip("/") != resource_url():
            raise AuthorizeError("invalid_target", "This server only issues tokens for its own /mcp resource.")
        req = sign_request({
            "c": client.client_id, "r": str(params.redirect_uri), "x": params.redirect_uri_provided_explicitly, "s": scopes, "st": params.state,
            "ch": params.code_challenge, "res": params.resource or resource_url(),
        })
        return f"{issuer_url()}/oauth/consent?req={req}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        return await run_in_threadpool(redeem_code, client.client_id or "", authorization_code)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        try:
            return await run_in_threadpool(exchange_code, authorization_code)
        except _Fail as exc:
            raise TokenError(exc.error, exc.description) from None  # type: ignore[arg-type]

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        return await run_in_threadpool(load_refresh, client.client_id or "", refresh_token)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        assert isinstance(refresh_token, CatchRefreshToken)
        try:
            return await run_in_threadpool(exchange_refresh, refresh_token, scopes)
        except _Fail as exc:
            raise TokenError(exc.error, exc.description) from None  # type: ignore[arg-type]

    async def load_access_token(self, token: str) -> AccessToken | None:
        found = await run_in_threadpool(_access_lookup, token)
        if found is None:
            return None
        principal, client_id = found
        return AccessToken(token=token, client_id=client_id, scopes=["catch:write", "catch:read"] if principal.scope == "write" else ["catch:read"], subject=principal.owner_id, resource=resource_url())

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await run_in_threadpool(revoke, token.token)


provider = CatchOAuthProvider()


def redirect_after_decision(req: dict, *, code: Optional[str], error: Optional[str] = None) -> str:
    extra = {"state": req["st"]} if req.get("st") else {}
    if code:
        return construct_redirect_uri(req["r"], code=code, **extra)
    return construct_redirect_uri(req["r"], error=error or "access_denied", **extra)
