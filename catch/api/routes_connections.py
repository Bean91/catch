"""Settings → Connections (session 25; docs/provider-connections.md).

Cookie / bearer-JWT only, like the AI-provider routes: a device token, an MCP client and a coach token never reach these. No
response ever contains a token, key or code — only a masked card (last four characters of a long key, a status, dates)."""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, SecretStr
from sqlmodel import Session

from catch.api.ratelimit import rate_limit
from catch.api.deps import get_db, require_auth
from catch.coach import limits
from catch.core import oauth_state, tenant
from catch.core.config import settings
from catch.core.owner import current_owner_id
from catch.sync import connections
from catch.sync.providers import available

logger = logging.getLogger("catch.connections")
router = APIRouter(dependencies=[Depends(require_auth)])
OAUTH_PROVIDERS = ("withings", "whoop", "concept2")


def _provider_or_404(provider: str) -> str:
    if provider not in connections.PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    return provider


def _throttle(owner_id: str) -> None:
    try:
        limits.check_rate(owner_id, "admin")
    except limits.LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.message) from None


class CredentialBody(BaseModel):
    api_key: SecretStr
    expires_on: str | None = None


class ExpiryBody(BaseModel):
    expires_on: str | None = None


def _expiry(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail="Enter the expiry as a date (YYYY-MM-DD).") from None


@router.get("/api/connections")
def list_connections(db: Session = Depends(get_db)):
    return {"deployment": "public" if tenant.is_public() else "personal", "connections": connections.list_cards(db)}


@router.put("/api/connections/{provider}/credential")
def put_credential(provider: str, body: CredentialBody, db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    """Garmin Personal API key, or a Concept2 personal token. Validated against the provider first; the secret is never echoed."""
    if _provider_or_404(provider) not in ("garmin", "concept2"):
        raise HTTPException(status_code=422, detail="This provider connects through its own sign-in page.")
    if not available(provider):
        raise HTTPException(status_code=404, detail="Not available on this server")
    _throttle(owner_id)
    try:
        return connections.connect_with_credential(db, provider, body.api_key.get_secret_value(), expires_on=_expiry(body.expires_on))
    except connections.Rejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.put("/api/connections/{provider}/expiry")
def put_expiry(provider: str, body: ExpiryBody, db: Session = Depends(get_db)):
    """The date a Garmin key expires (Garmin doesn't expose it; you choose it when creating the key) — drives the reminder."""
    if _provider_or_404(provider) != "garmin" or not connections.is_connected(db, provider):
        raise HTTPException(status_code=404, detail="Not connected")
    connections.set_credential_expiry(db, provider, _expiry(body.expires_on))
    return connections.card(db, provider)


@router.post("/api/connections/{provider}/oauth/start")
def oauth_start(provider: str, response: Response, native: bool = False, return_to: str | None = None, owner_id: str = Depends(current_owner_id)):
    """Bearer-authenticated; returns the provider's authorize URL (the browser then navigates there — a redirect from here
    couldn't carry the bearer). Sets the signed state cookie the callback needs."""
    if _provider_or_404(provider) not in OAUTH_PROVIDERS:
        raise HTTPException(status_code=422, detail="This provider uses a pasted key, not a sign-in page.")
    _throttle(owner_id)
    if native:
        return {"authorize_url": native_start_url(provider, owner_id)}
    if return_to is not None and return_to not in oauth_state.RETURN_PATHS:
        raise HTTPException(status_code=422, detail="Unknown return page.")
    url = authorize_url_for(provider, response, owner_id, return_to=return_to)
    return {"authorize_url": url}


def _configured(provider: str) -> bool:
    from catch.sync import concept2_client, whoop_client, withings_client

    return {"withings": withings_client.configured, "whoop": whoop_client.configured, "concept2": concept2_client.oauth_configured}[provider]()


def _provider_authorize_url(provider: str, nonce: str) -> str:
    from catch.sync import concept2_client, whoop_client, withings_client

    return {"withings": withings_client.authorize_url, "whoop": whoop_client.authorize_url, "concept2": concept2_client.authorize_url}[provider](nonce)


def native_start_url(provider: str, owner_id: str) -> str:
    """The store app's version of "start": a single-use ticket URL on this server for the system browser to open (see oauth_state)."""
    if not _configured(provider):
        raise HTTPException(status_code=409, detail=f"{provider.capitalize()} sign-in isn't set up on this server.")
    ticket = oauth_state.make_ticket(owner_id, provider, oauth_state.new_nonce(provider))
    return f"{settings.base_url.rstrip('/')}/auth/{provider}/native-start?ticket={ticket}"


def authorize_url_for(provider: str, response: Response, owner_id: str, return_to: str | None = None) -> str:
    from catch.sync import concept2_client, whoop_client, withings_client

    configured = {"withings": withings_client.configured, "whoop": whoop_client.configured, "concept2": concept2_client.oauth_configured}[provider]
    if not configured():
        raise HTTPException(status_code=409, detail=f"{provider.capitalize()} sign-in isn't set up on this server.")
    nonce = oauth_state.new_nonce(provider)
    url = {"withings": withings_client.authorize_url, "whoop": whoop_client.authorize_url, "concept2": concept2_client.authorize_url}[provider](nonce)
    response.set_cookie(oauth_state.cookie_name(provider), oauth_state.make(owner_id, provider, nonce, return_to=return_to), **oauth_state.cookie_kwargs())
    return url


@router.post("/api/connections/{provider}/test")
def test_connection(provider: str, db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    _provider_or_404(provider)
    _throttle(owner_id)
    return connections.test_connection(db, provider)


@router.post("/api/connections/{provider}/sync")
def sync_now(provider: str, owner_id: str = Depends(current_owner_id)):
    from catch.sync.scheduler import run_sync

    _provider_or_404(provider)
    _throttle(owner_id)
    return run_sync(provider, manual=True)


@router.delete("/api/connections/{provider}")
def disconnect(provider: str, db: Session = Depends(get_db)):
    _provider_or_404(provider)
    try:
        return connections.disconnect_provider(db, provider)
    except connections.Rejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


callback_router = APIRouter()  # deliberately unauthenticated: identity comes from the signed state cookie, never from a body or query


@callback_router.get("/auth/{provider}/native-start", dependencies=[rate_limit("callback", by="ip")])
def oauth_native_start(provider: str, ticket: str | None = None):
    """Runs in the SYSTEM browser the store app opened. Redeems the ticket, sets the signed state cookie here (the one place it can
    be set so the callback sees it), and sends the browser on to the provider. Public deployment only."""
    from fastapi.responses import RedirectResponse

    if not tenant.is_public() or provider not in OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        owner, nonce = oauth_state.redeem_ticket(ticket, provider)
    except oauth_state.OAuthStateError:
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in link") from None
    if not _configured(provider):
        raise HTTPException(status_code=409, detail=f"{provider.capitalize()} sign-in isn't set up on this server.")
    response = RedirectResponse(_provider_authorize_url(provider, nonce), status_code=302)
    response.set_cookie(oauth_state.cookie_name(provider), oauth_state.make(owner, provider, nonce, native=True), **oauth_state.cookie_kwargs())
    return response


@callback_router.get("/auth/{provider}/callback", dependencies=[rate_limit("callback", by="ip")])
def oauth_callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: Session = Depends(get_db),  # a session begins lazily, so the owner set below is what its first statement sees
):
    """Runs without a bearer token. The owner is established *inside* this handler from the verified cookie (a sync dependency would
    set it in a thread copy of the context and lose it)."""
    from fastapi.responses import RedirectResponse

    from catch.core.models import UserProfile
    from catch.sync import concept2_client, whoop_client, withings_client

    if provider not in OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    try:
        owner, from_app, return_to = oauth_state.verify_details(request.cookies.get(oauth_state.cookie_name(provider)), provider, state)
    except oauth_state.OAuthStateError:
        raise HTTPException(status_code=400, detail="Invalid or missing OAuth state") from None

    def done(result: str) -> RedirectResponse:
        # Started from the store app: hand control back to it through its custom scheme (the app also handles https links, but a
        # redirect that stays on this domain is opened by the browser, not by the app).
        target = f"{settings.native_url_scheme}://settings/connections" if from_app else oauth_state.RETURN_PATHS[return_to]
        redirect = RedirectResponse(f"{target}?provider={provider}&result={result}", status_code=303)
        redirect.delete_cookie(oauth_state.cookie_name(provider), path="/")
        return redirect

    if error or not code:
        return done("denied")
    exchange = {"withings": withings_client.exchange_code, "whoop": whoop_client.exchange_code, "concept2": concept2_client.exchange_code}[provider]
    with tenant.use_owner(owner):
        try:
            if tenant.is_public() and session.get(UserProfile, owner) is None:
                return done("failed")  # the account was deleted between start and callback
            exchange(session, code)
        except Exception as exc:  # noqa: BLE001 — a fixed outcome for the browser; the class name (never the code, a token or a body) for the operator
            session.rollback()
            outcome = _callback_outcome(exc)
            logger.warning("%s callback failed: %s (%s)", provider, type(exc).__name__, outcome)
            return done(outcome)
        # The tokens are stored and committed: from here the account IS connected, whatever happens to queueing the history import
        # (the next sync retries that), so a failure below must not tell the user it didn't work.
        try:
            from catch.sync.scheduler import start_backfill

            start_backfill(session, provider)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.warning("%s history import couldn't be queued: %s", provider, type(exc).__name__)
    return done("connected")


def _callback_outcome(exc: Exception) -> str:
    """failed | server_setup (the operator's app credentials or callback URL) | expired (the provider refused the one-time code —
    Withings' lives 30 seconds)."""
    from catch.sync import withings_client

    if isinstance(exc, withings_client.WithingsAppMisconfigured):
        return "server_setup"
    if isinstance(exc, withings_client.WithingsCodeRejected):
        return "expired"
    return "failed"
