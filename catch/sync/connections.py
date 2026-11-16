"""Per-user provider connections (session 25; docs/provider-connections.md).

The ONE place a provider credential is stored, sealed, resolved or removed. The REST routes, the sync engine and the coach/MCP
tools all call this module; none of them handle a plaintext secret except through `credential()` / `oauth_tokens()` here, and
nothing returned from `card()` / `list_cards()` ever contains one.

Credential order: a connection row first. Only the *personal* deployment may then fall back to a legacy `oauth_tokens` row (adopted
once, and removed in the same transaction — rotating refresh tokens must never live in two places) or to an environment credential
(Garmin key / Concept2 token). The public deployment never reads the environment for a user's credential.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from catch.core import secret_store, security, tenant
from catch.core.config import settings
from catch.core.models import OAuthToken, ProviderConnection, SyncState
from catch.core.redact import register_secret

logger = logging.getLogger("catch.connections")

PROVIDERS = ("garmin", "withings", "concept2", "whoop")

CONNECTED, NEEDS_RECONNECT, ERROR, RATE_LIMITED = "connected", "needs_reconnect", "error", "rate_limited"
STATUSES = (CONNECTED, NEEDS_RECONNECT, ERROR, RATE_LIMITED)

# Fixed vocabulary: provider-supplied text never reaches the database or the browser.
DETAILS = {
    "backfilling": "Importing your history in small steps.",
    "from_environment": "Using the credential in this server's environment.",
    "key_rejected": "The provider rejected the saved credential.",
    "key_expired": "The saved key has expired.",
    "authorization_revoked": "The provider no longer accepts this authorization.",
    "unreachable": "The provider couldn't be reached.",
    "rate_limited": "The provider is rate-limiting Catch; it will retry on its own.",
    "sync_failed": "The last sync failed.",
}

AUTH_METHODS = {
    "garmin": ("api_key",),
    "withings": ("oauth",),
    "concept2": ("oauth", "personal_token"),
    "whoop": ("oauth",),
}
# Slots of a sealed value on the row. The slot is part of the AAD, so a blob moved between slots (or owners, or providers) fails.
_SLOTS = {"access": "access_enc", "refresh": "refresh_enc", "credential": "credential_enc"}


class ConnectionError_(RuntimeError):
    """A connection-level problem with a fixed, user-safe message."""


@dataclass
class OAuthTokens:
    access: str | None
    refresh: str | None
    expires_at: datetime | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _owner() -> str:
    return tenant.current_owner()


def _scope(provider: str, slot: str) -> str:
    return f"{provider}:{slot}"


def _seal(provider: str, slot: str, plaintext: str) -> tuple[str, str]:
    register_secret(plaintext)
    return secret_store.seal(plaintext, owner_id=_owner(), provider=_scope(provider, slot), purpose=secret_store.CONNECTION_PURPOSE)


def _open(row: ProviderConnection, slot: str) -> str | None:
    blob = getattr(row, _SLOTS[slot])
    if not blob:
        return None
    value = secret_store.open_sealed(blob, owner_id=row.owner_id, provider=_scope(row.provider, slot), purpose=secret_store.CONNECTION_PURPOSE)
    register_secret(value)
    return value


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError("Unknown provider.")


# -- reads --------------------------------------------------------------------------------------------------------------


def _env_credential(provider: str) -> str | None:
    """The personal install's server-wide credential. NEVER consulted in a public deployment."""
    if tenant.is_public():
        return None
    return {"garmin": settings.garmin_api_key, "concept2": settings.concept2_access_token}.get(provider) or None


def _adopt_legacy(session: Session, provider: str) -> ProviderConnection | None:
    """Personal only: move a pre-session-25 `oauth_tokens` row (Fernet) or an environment credential into a connection row."""
    if tenant.is_public():
        return None
    legacy = session.get(OAuthToken, tenant.pk(provider))
    if provider in ("withings", "whoop") and legacy is not None and legacy.refresh_token_enc:
        row = ProviderConnection(provider=provider, auth_method="oauth", status=CONNECTED)
        access, refresh = security.decrypt(legacy.access_token_enc), security.decrypt(legacy.refresh_token_enc)
        row.access_enc, row.key_id = _seal(provider, "access", access)
        row.refresh_enc, _ = _seal(provider, "refresh", refresh)
        row.expires_at = legacy.expires_at
        session.add(row)
        session.delete(legacy)  # one live copy only: rotating refresh tokens would diverge otherwise
        session.commit()
        return row
    if provider in ("garmin", "concept2") and _env_credential(provider):
        if provider == "garmin" and legacy is not None:
            session.delete(legacy)  # the old cached JWT; it is re-derived from the key
        row = ProviderConnection(
            provider=provider,
            auth_method="api_key" if provider == "garmin" else "personal_token",
            status=CONNECTED,
            status_detail="from_environment",
        )
        session.add(row)
        session.commit()
        return row
    return None


def get(session: Session, provider: str) -> ProviderConnection | None:
    _check_provider(provider)
    row = session.get(ProviderConnection, tenant.pk(provider))
    return row if row is not None else _adopt_legacy(session, provider)


def is_connected(session: Session, provider: str) -> bool:
    return get(session, provider) is not None


def credential(session: Session, provider: str) -> str:
    """The user-supplied secret (Garmin key, Concept2 personal token), decrypted. Server-side only."""
    row = get(session, provider)
    if row is None:
        raise ConnectionError_("Not connected.")
    value = _open(row, "credential")
    if value:
        return value
    env = _env_credential(provider) if row.status_detail == "from_environment" else None
    if env:
        register_secret(env)
        return env
    raise ConnectionError_("Not connected.")


def oauth_tokens(session: Session, provider: str, *, for_update: bool = False) -> OAuthTokens:
    """Tokens of an OAuth connection. `for_update` takes a row lock so two replicas can't both spend a rotating refresh token
    (a no-op on SQLite, where the per-process lock in the client is the guard)."""
    if for_update and get(session, provider) is not None:
        session.exec(select(ProviderConnection).where(ProviderConnection.provider == provider).with_for_update()).first()
    row = get(session, provider)
    if row is None:
        raise ConnectionError_("Not connected.")
    if for_update:
        session.refresh(row)
    return OAuthTokens(_open(row, "access"), _open(row, "refresh"), _aware(row.expires_at))


# -- writes -------------------------------------------------------------------------------------------------------------


def _row_for_write(session: Session, provider: str, auth_method: str) -> ProviderConnection:
    row = session.get(ProviderConnection, tenant.pk(provider))
    if row is None:
        row = ProviderConnection(provider=provider, auth_method=auth_method)
        session.add(row)
    row.auth_method = auth_method
    return row


def store_oauth(
    session: Session,
    provider: str,
    *,
    access: str,
    refresh: str | None,
    expires_in: int | None,
    scopes: str | None = None,
    account_id: str | None = None,
) -> None:
    """Persist a (possibly rotated) token pair and commit before returning. A missing `refresh` keeps the stored one."""
    _check_provider(provider)
    legacy = None if tenant.is_public() else session.get(OAuthToken, tenant.pk(provider))
    row = _row_for_write(session, provider, "oauth")
    row.access_enc, row.key_id = _seal(provider, "access", access)
    if refresh:
        row.refresh_enc, _ = _seal(provider, "refresh", refresh)
    row.expires_at = _now() + timedelta(seconds=int(expires_in or 3600))
    if scopes is not None:
        row.scopes_json = json.dumps(sorted(set(scopes.replace(",", " ").split())))
    if account_id:
        row.account_id = account_id
    row.credential_enc = None
    row.status, row.status_detail = CONNECTED, None
    row.last_validated_at = row.updated_at = _now()
    if legacy is not None:
        session.delete(legacy)
    session.commit()


def store_credential(
    session: Session,
    provider: str,
    secret: str,
    *,
    auth_method: str,
    account_id: str | None = None,
    scopes: list[str] | None = None,
    expires_on: date | None = None,
) -> None:
    """Replace the user-supplied secret (already validated by the caller). Resets status and any cached access token."""
    _check_provider(provider)
    if auth_method not in AUTH_METHODS[provider]:
        raise ConnectionError_("That connection method isn't available for this provider.")
    row = _row_for_write(session, provider, auth_method)
    row.credential_enc, row.key_id = _seal(provider, "credential", secret)
    row.last4 = secret_store.mask(secret)
    row.access_enc = row.refresh_enc = None
    row.expires_at = None
    row.account_id = account_id or row.account_id
    row.scopes_json = json.dumps(sorted(scopes)) if scopes is not None else row.scopes_json
    row.credential_expires_on = expires_on
    row.status, row.status_detail = CONNECTED, None
    row.last_validated_at = row.updated_at = _now()
    row.connected_at = _now() if row.connected_at is None else row.connected_at
    session.commit()


def store_access_cache(session: Session, provider: str, token: str, expires_at: datetime) -> None:
    """Garmin: the 24 h JWT derived from the key, kept sealed so a sync doesn't re-exchange the key every run."""
    row = get(session, provider)
    if row is None:
        raise ConnectionError_("Not connected.")
    row.access_enc, _ = _seal(provider, "access", token)
    row.expires_at = expires_at
    row.updated_at = _now()
    session.commit()


def cached_access(session: Session, provider: str) -> OAuthTokens:
    row = get(session, provider)
    if row is None:
        raise ConnectionError_("Not connected.")
    return OAuthTokens(_open(row, "access"), None, _aware(row.expires_at))


def set_credential_expiry(session: Session, provider: str, expires_on: date | None) -> None:
    row = get(session, provider)
    if row is None:
        raise ConnectionError_("Not connected.")
    row.credential_expires_on = expires_on
    session.commit()


def mark(session: Session, provider: str, status: str, detail: str | None = None) -> None:
    if status not in STATUSES or (detail is not None and detail not in DETAILS):
        raise ValueError("Unknown status.")
    row = session.get(ProviderConnection, tenant.pk(provider))
    if row is None:
        return
    row.status, row.status_detail = status, detail
    row.updated_at = _now()
    session.commit()


def mark_ok(session: Session, provider: str) -> None:
    """A successful sync: healthy again, and a finished history import stops saying 'backfilling'."""
    row = session.get(ProviderConnection, tenant.pk(provider))
    if row is None:
        return
    state = session.get(SyncState, tenant.pk(provider))
    importing = bool(state and state.backfill_cursor)
    row.status = CONNECTED
    row.status_detail = "backfilling" if importing else (row.status_detail if row.status_detail == "from_environment" else None)
    row.last_validated_at = row.updated_at = _now()
    session.commit()


def delete(session: Session, provider: str) -> bool:
    """Forget the credentials and the sync cursor. Imported Catch records are never touched."""
    row = session.get(ProviderConnection, tenant.pk(provider))
    legacy = None if tenant.is_public() else session.get(OAuthToken, tenant.pk(provider))
    existed = row is not None or legacy is not None
    if row is not None:
        session.delete(row)
    if legacy is not None:
        session.delete(legacy)
    state = session.get(SyncState, tenant.pk(provider))
    if state is not None:
        session.delete(state)  # a disconnected source must not be reported as a stale sync
    session.commit()
    return existed


# -- cards (everything a browser, the coach or an MCP client may see) ----------------------------------------------------


def _iso(dt: datetime | None) -> str | None:
    dt = _aware(dt)
    return dt.isoformat() if dt else None


def _expiry_on(session: Session, row: ProviderConnection | None) -> str | None:
    if row is None:
        return None
    if row.credential_expires_on:
        return row.credential_expires_on.isoformat()
    if row.provider == "garmin" and not tenant.is_public():
        # The Pi's pre-session-25 reminder (a settings row) still counts for a key kept in .env.
        from catch.core.settings_store import get_settings

        value = get_settings(session).get("garmin_key_expires_on")
        return str(value) if value else None
    return None


def card(session: Session, provider: str) -> dict:
    from catch.sync.providers import metadata, oauth_available

    row = get(session, provider)
    state = session.get(SyncState, tenant.pk(provider))
    meta = metadata(provider)
    out = {
        "provider": provider,
        "label": meta["label"],
        "auth_methods": list(AUTH_METHODS[provider]),
        "available": meta["available"](),
        "oauth_available": oauth_available(provider),
        "connected": row is not None,
        "status": row.status if row else "disconnected",
        "status_detail": row.status_detail if row else None,
        "status_text": DETAILS.get(row.status_detail) if row and row.status_detail else None,
        "auth_method": row.auth_method if row else None,
        "last4": row.last4 if row else "",
        "scopes": json.loads(row.scopes_json) if row and row.scopes_json else [],
        "account_connected_at": _iso(row.connected_at) if row else None,
        "credential_expires_on": _expiry_on(session, row),
        "token_expires_at": _iso(row.expires_at) if row and row.auth_method == "oauth" else None,
        "last_attempt_at": _iso(state.last_attempt_at) if state else None,
        "last_success_at": _iso(state.last_success_at) if state else None,
        "last_error": state.last_error if state else None,
        "consecutive_failures": state.consecutive_failures if state else 0,
        "next_attempt_at": _iso(state.next_attempt_at) if state else None,
        "importing_history_from": state.backfill_cursor if state and state.backfill_cursor else None,
        "capabilities": meta["capabilities"],
        "limitations": meta["limitations"],
        "notes": meta["notes"],
    }
    return out


def list_cards(session: Session) -> list[dict]:
    return [card(session, p) for p in PROVIDERS]


def sync_summary(session: Session) -> list[dict]:
    """The compact per-provider sync view the coach tools return."""
    keys = ("provider", "label", "connected", "status", "status_text", "last_success_at", "last_attempt_at", "last_error", "consecutive_failures", "next_attempt_at", "importing_history_from")
    return [{k: c[k] for k in keys} for c in list_cards(session)]


# -- operations shared by the REST routes and the coach tools ----------------------------------------------------------------


class Rejected(ConnectionError_):
    """The candidate credential was refused; nothing was saved. The message is fixed text, never the provider's."""


def connect_with_credential(session: Session, provider: str, secret: str, *, expires_on: date | None = None, auth_method: str | None = None) -> dict:
    """Validate a user-supplied secret against the provider *before* it replaces anything, then seal and store it and queue the
    history import. A typo therefore never destroys a working connection."""
    from catch.sync.providers import available, base

    _check_provider(provider)
    method = auth_method or ("api_key" if provider == "garmin" else "personal_token")
    if provider not in ("garmin", "concept2") or method not in AUTH_METHODS[provider] or method == "oauth":
        raise Rejected("This provider connects through its own sign-in page, not a pasted key.")
    if not available(provider):
        raise Rejected("This provider isn't available on this server.")
    secret = secret.strip()
    if not secret:
        raise Rejected("The key is empty.")
    account_id, scopes = None, None
    try:
        if provider == "garmin":
            from catch.sync.garmin_client import KEY_HELP, exchange_key

            token, token_expiry, claims = exchange_key(secret)
            account_id = str(claims["garmin_guid"]) if claims.get("garmin_guid") else None
            scope = claims.get("scope")
            scopes = scope.split() if isinstance(scope, str) else (list(scope) if isinstance(scope, list) else None)
        else:
            from catch.sync.concept2_client import validate_token

            account_id = validate_token(secret).get("account_id")
    except base.ProviderAuthError:
        raise Rejected(KEY_HELP if provider == "garmin" else "Concept2 rejected that token. Create a new one under Edit Profile → Applications.") from None
    except base.ProviderRateLimited:
        raise Rejected("The provider is rate-limiting right now. Wait a minute and try again.") from None
    except base.ProviderError:
        raise Rejected("Couldn't reach the provider to check the key. Nothing was saved; try again shortly.") from None
    store_credential(session, provider, secret, auth_method=method, account_id=account_id, scopes=scopes, expires_on=expires_on)
    if provider == "garmin":
        store_access_cache(session, provider, token, token_expiry)
    from catch.sync.scheduler import start_backfill

    start_backfill(session, provider)
    return card(session, provider)


def test_connection(session: Session, provider: str) -> dict:
    """Does the stored authorization still work? Counts/booleans only — never an identifier, token or name."""
    from catch.sync.providers import base

    row = get(session, provider)
    if row is None:
        return {"connected": False, "ok": False, "message": "Not connected."}
    try:
        if provider == "garmin":
            from catch.sync.garmin_client import exchange_key

            exchange_key(credential(session, provider))
        elif provider == "concept2":
            from catch.sync.concept2_client import _client, get_profile

            with _client(session) as http:
                get_profile(http)
        elif provider == "whoop":
            from catch.sync import whoop_client

            whoop_client.check(session)
        else:
            from catch.sync import withings_client

            withings_client.get_access_token(session)
    except base.ProviderAuthError as exc:
        mark(session, provider, NEEDS_RECONNECT, getattr(exc, "detail", "key_rejected"))
        return {"connected": True, "ok": False, "needs_reconnect": True, "message": str(exc)}
    except base.ProviderRateLimited:
        return {"connected": True, "ok": False, "message": "The provider is rate-limiting right now; try again shortly."}
    except Exception:  # noqa: BLE001 — fixed text only
        return {"connected": True, "ok": False, "message": "Couldn't reach the provider."}
    mark_ok(session, provider)
    return {"connected": True, "ok": True, "message": "Connection works."}


def disconnect_provider(session: Session, provider: str) -> dict:
    """Revoke where the provider supports it, then forget every credential. Imported Catch data is never deleted."""
    _check_provider(provider)
    revoked = False
    if provider == "whoop" and get(session, provider) is not None:
        from catch.sync import whoop_client

        return whoop_client.disconnect(session)
    existed = delete(session, provider)
    return {"revoked": revoked, "was_connected": existed}


def revoke_all_for_account_deletion(session: Session) -> None:
    """Best effort before an account is deleted: end live grants at providers that offer revocation (Whoop). Never blocks deletion."""
    for provider in PROVIDERS:
        try:
            if provider == "whoop" and get(session, provider) is not None:
                from catch.sync import whoop_client

                whoop_client.disconnect(session)
        except Exception:  # noqa: BLE001
            logger.warning("couldn't revoke %s during account deletion", provider)
            session.rollback()
