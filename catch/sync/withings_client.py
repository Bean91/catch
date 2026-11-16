from __future__ import annotations

import hashlib
import hmac
import threading
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

import httpx
from sqlmodel import Session

from catch.core.config import settings
from catch.sync import connections
from catch.sync.providers.base import ProviderAuthError, ProviderError, ProviderRateLimited, ProviderUnavailable
from catch.sync.upsert import upsert_body_comp

AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
SIGNATURE_URL = "https://wbsapi.withings.net/v2/signature"
OAUTH_URL = "https://wbsapi.withings.net/v2/oauth2"
MEASURE_URL = "https://wbsapi.withings.net/measure"
SOURCE = "withings"

# See docs/withings-endpoints.md: 1 and 6 and 88 are confirmed against Withings' own docs
# example; 8/76/77 are the long-standing standard codes, unconfirmed against a live response
# until the first real sync.
MEASTYPE_MAP = {1: "weight_kg", 6: "fat_pct", 8: "fat_kg", 76: "muscle_kg", 77: "hydration_kg", 88: "bone_kg"}
MEASTYPES = ",".join(str(k) for k in MEASTYPE_MAP)


class WithingsError(ProviderError):
    pass


class WithingsReconnectNeeded(WithingsError, ProviderAuthError):
    detail = "authorization_revoked"


# Withings answers HTTP 200 with a non-zero JSON `status`. 601 ("too many requests") and 401 ("invalid or expired access token") are
# from memory of Withings' error list, NOT confirmed by a live response — so only those two get special handling; any other non-zero
# status is a plain error (retried with backoff, reported by code only, never the body). A refused *refresh* is the case that really
# needs a reconnect and is handled separately in `_request_token`.
_RATE_STATUS = 601
_AUTH_STATUSES = (401,)
_refresh_lock = threading.Lock()


def _check_status(data: dict, action: str) -> None:
    status = data.get("status")
    if status == _RATE_STATUS:
        raise ProviderRateLimited("Withings is rate-limiting Catch; it will retry on its own.")
    if status in _AUTH_STATUSES:
        raise WithingsReconnectNeeded("Withings refused the authorization. Reconnect Withings.")
    if status != 0:
        # Withings' error responses carry the real reason in a top-level "error" field
        # (e.g. {"status": 503, "error": "Invalid Params"}) that status alone doesn't explain.
        detail = data.get("error")
        suffix = f" ({detail})" if detail else ""
        raise WithingsError(f"Withings {action} failed: status={status}{suffix}")


def _sign(*parts: str) -> str:
    message = ",".join(parts)
    return hmac.new(settings.withings_client_secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def authorize_url(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.withings_client_id,
        "scope": "user.metrics",
        "redirect_uri": settings.withings_redirect_uri,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _get_nonce() -> str:
    timestamp = str(int(time.time()))
    signature = _sign("getnonce", settings.withings_client_id, timestamp)
    resp = _post(
        SIGNATURE_URL,
        data={"action": "getnonce", "client_id": settings.withings_client_id, "timestamp": timestamp, "signature": signature},
    )
    data = resp.json()
    _check_status(data, "getnonce")
    return data["body"]["nonce"]


def _post(url: str, **kwargs) -> httpx.Response:
    try:
        resp = httpx.post(url, timeout=30.0, **kwargs)
    except httpx.HTTPError:
        raise ProviderUnavailable("Couldn't reach Withings.") from None
    if resp.status_code == 429:
        raise ProviderRateLimited("Withings is rate-limiting Catch; it will retry on its own.")
    if resp.status_code >= 500:
        raise ProviderUnavailable("Withings had a problem; Catch will retry.")
    resp.raise_for_status()
    return resp


def _request_token(session: Session, *, grant_type: str, code: str | None = None, refresh_token: str | None = None) -> str:
    nonce = _get_nonce()
    signature = _sign("requesttoken", settings.withings_client_id, nonce)
    params = {
        "action": "requesttoken",
        "client_id": settings.withings_client_id,
        "grant_type": grant_type,
        "nonce": nonce,
        "signature": signature,
    }
    if grant_type == "authorization_code":
        params["code"] = code
        params["redirect_uri"] = settings.withings_redirect_uri
    else:
        params["refresh_token"] = refresh_token

    resp = _post(OAUTH_URL, data=params)
    data = resp.json()
    try:
        _check_status(data, "requesttoken")
    except WithingsError as exc:
        if grant_type == "refresh_token" and not isinstance(exc, WithingsReconnectNeeded):
            # A refused refresh can't be retried into working: the old token is dead once a newer one exists.
            raise WithingsReconnectNeeded("Withings refused the saved authorization. Reconnect Withings.") from None
        raise
    body = data["body"]
    # Withings' refresh tokens rotate (the old one survives only ~8 h): persist the new pair before anything else.
    connections.store_oauth(
        session,
        SOURCE,
        access=body["access_token"],
        refresh=body["refresh_token"],
        expires_in=int(body.get("expires_in", 10800)),
        scopes=body.get("scope"),
        account_id=str(body["userid"]) if body.get("userid") is not None else None,
    )
    return body["access_token"]


def exchange_code(session: Session, code: str) -> str:
    return _request_token(session, grant_type="authorization_code", code=code)


def get_access_token(session: Session) -> str:
    try:
        tokens = connections.oauth_tokens(session, SOURCE)
    except connections.ConnectionError_:
        raise WithingsReconnectNeeded("Withings isn't connected. Connect it in Settings → Connections.") from None
    fresh = lambda t: t.access and t.expires_at and t.expires_at > datetime.now(timezone.utc) + timedelta(minutes=5)  # noqa: E731
    if fresh(tokens):
        return tokens.access
    with _refresh_lock:
        tokens = connections.oauth_tokens(session, SOURCE, for_update=True)  # re-read: another caller may have rotated it
        if fresh(tokens):
            return tokens.access
        if not tokens.refresh:
            raise WithingsReconnectNeeded("Withings authorization expired. Reconnect Withings.")
        return _request_token(session, grant_type="refresh_token", refresh_token=tokens.refresh)


def _fetch_measure_pages(access_token: str, **extra_params: str) -> Iterator[dict]:
    params = {"action": "getmeas", "meastypes": MEASTYPES, "category": 1, **extra_params}
    offset = None
    while True:
        if offset:
            params["offset"] = offset
        resp = _post(MEASURE_URL, data=params, headers={"Authorization": f"Bearer {access_token}"})
        data = resp.json()
        _check_status(data, "getmeas")
        body = data.get("body", {})
        for grp in body.get("measuregrps", []):
            yield grp
        if not body.get("more"):
            return
        offset = body.get("offset")


def sync(session: Session, lastupdate: int | None = None, days: int | None = None, window: tuple[date, date] | None = None) -> int:
    access_token = get_access_token(session)
    if window is not None:
        start, end = window
        extra = {
            "startdate": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
            "enddate": int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400,
        }
    elif days is not None:
        now = int(time.time())
        extra = {"startdate": now - days * 86400, "enddate": now}
    elif lastupdate:
        extra = {"lastupdate": lastupdate}
    else:
        extra = {}
    count = 0
    for grp in _fetch_measure_pages(access_token, **extra):
        values: dict[str, float] = {}
        for m in grp.get("measures", []):
            column = MEASTYPE_MAP.get(m.get("type"))
            if column:
                values[column] = m["value"] * (10 ** m["unit"])
        if not values:
            continue
        ts = datetime.fromtimestamp(grp["date"], tz=timezone.utc)
        upsert_body_comp(session, SOURCE, str(grp.get("grpid", grp["date"])), ts=ts, **values)
        count += 1
    return count


def configured() -> bool:
    return bool(settings.withings_client_id and settings.withings_client_secret and settings.withings_redirect_uri)


def disconnect(session: Session) -> dict:
    """Forgets Catch's tokens. Withings' public docs describe no revoke call, so the grant itself stays on the user's Withings
    account until they remove it there (docs/withings-endpoints.md)."""
    return {"revoked": False, "was_connected": connections.delete(session, SOURCE)}
