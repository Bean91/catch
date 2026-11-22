from __future__ import annotations

import hashlib
import hmac
import logging
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
logger = logging.getLogger("catch.withings")

# Codes from Withings' getmeas meastype table (developer.withings.com/openapi.yaml). 1/6/8/76/77/88 were also checked against a live
# account on 2026-11-22: muscle + bone + fat mass sum to the weight. 5 (fat-free mass) only fills fat mass when 8 is absent.
MEASTYPE_MAP = {1: "weight_kg", 6: "fat_pct", 8: "fat_kg", 76: "muscle_kg", 77: "hydration_kg", 88: "bone_kg"}
FAT_FREE_MASS = 5
MEASTYPES = ",".join(str(k) for k in sorted((*MEASTYPE_MAP, FAT_FREE_MASS)))
# `attrib` 1: captured by a shared scale and possibly someone else's weigh-in; 4: typed in at Withings account creation. Neither is
# reliably this athlete's measurement.
SKIPPED_ATTRIBS = frozenset({1, 4})


class WithingsError(ProviderError):
    detail = "sync_failed"


class WithingsReconnectNeeded(WithingsError, ProviderAuthError):
    detail = "authorization_revoked"


class WithingsAppMisconfigured(WithingsError):
    """Withings refused Catch's *app* credentials (signature, client id, callback URL): an operator problem, not the user's, so it is
    never reported as "reconnect"."""

    detail = "app_misconfigured"


class WithingsCodeRejected(WithingsError):
    """The authorization code was refused: Withings codes live 30 seconds and work once."""


# Withings answers HTTP 200 with a non-zero JSON `status` and an "error" string. Families from the spec's status table; the strings
# were observed live on 2026-11-22 (docs/withings-endpoints.md): a bad signature, client id or callback URL is the app's fault; an
# invalid refresh/access token is the user's grant; 601 is rate limiting; 522 a timeout.
_RATE_STATUS = 601
_TIMEOUT_STATUS = 522
_AUTH_STATUSES = frozenset({100, 101, 102, 200, 401})
_APP_MARKERS = ("hmac", "signature", "nonce", "client_id", "redirect_uri", "client")
_GRANT_MARKERS = ("refresh_token", "invalid_token", "access_token")
_refresh_lock = threading.Lock()


def _check_status(data: dict, action: str) -> None:
    status = data.get("status")
    if status == 0:
        return
    error = str(data.get("error") or "")
    lowered = error.lower()
    # Withings' error text names a parameter, never a credential value; logged for the operator, never stored or shown.
    logger.warning("withings %s refused: status=%s %s", action, status, error[:120])
    if status == _RATE_STATUS:
        raise ProviderRateLimited("Withings is rate-limiting Catch; it will retry on its own.")
    if status == _TIMEOUT_STATUS:
        raise ProviderUnavailable("Withings timed out; Catch will retry.")
    # getnonce and revoke carry no user token: whatever Withings refuses there is the app's (live: a made-up client id answers
    # "invalid client id/secret"), never a reason to ask a user to reconnect.
    if action in ("getnonce", "revoke"):
        raise WithingsAppMisconfigured("Withings refused this server's app credentials. The server operator needs to fix them.")
    if any(marker in lowered for marker in _GRANT_MARKERS) or status in _AUTH_STATUSES:
        raise WithingsReconnectNeeded("Withings no longer accepts this authorization. Reconnect Withings.")
    if any(marker in lowered for marker in _APP_MARKERS):
        raise WithingsAppMisconfigured("Withings refused this server's app credentials. The server operator needs to fix them.")
    if action == "requesttoken" and "code" in lowered:
        raise WithingsCodeRejected("Withings refused the sign-in code. Start the connection again.")
    raise WithingsError(f"Withings {action} failed (status {status}).")


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
    # Only a refused *token* means the grant is gone (_check_status). A bad signature or a Withings hiccup during a refresh leaves the
    # stored refresh token unspent, so the next run can still use it — reporting "reconnect" there would be wrong (audit L-41).
    _check_status(data, "requesttoken")
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


DEFAULT_DAYS = 30


def _real_value(measure: dict) -> float:
    # value × 10^unit, divided rather than multiplied by a negative power so 72400 × 10^-3 is exactly 72.4.
    value, unit = measure["value"], int(measure.get("unit", 0))
    return float(value * 10**unit) if unit >= 0 else value / 10 ** (-unit)


def body_comp_values(group: dict) -> dict[str, float]:
    """One measure group → body_comp columns. Empty for a group that isn't reliably this athlete's (SKIPPED_ATTRIBS)."""
    if group.get("attrib") in SKIPPED_ATTRIBS:
        return {}
    values: dict[str, float] = {}
    fat_free = None
    for measure in group.get("measures", []):
        kind = measure.get("type")
        if kind == FAT_FREE_MASS:
            fat_free = _real_value(measure)
        elif kind in MEASTYPE_MAP:
            values[MEASTYPE_MAP[kind]] = _real_value(measure)
    if "fat_kg" not in values and fat_free is not None and values.get("weight_kg") and values["weight_kg"] >= fat_free:
        values["fat_kg"] = round(values["weight_kg"] - fat_free, 3)
    return values


def sync(session: Session, lastupdate: int | None = None, days: int | None = None, window: tuple[date, date] | None = None) -> int:
    """Upserts measure groups keyed on Withings' `grpid`, so a re-sync or an overlapping window never duplicates a row. With no
    cursor it reads a bounded `days` window — never the whole history in one go; history comes from the backfill's windows."""
    access_token = get_access_token(session)
    if window is not None:
        start, end = window
        extra = {
            "startdate": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
            "enddate": int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400,
        }
    elif lastupdate:
        extra = {"lastupdate": lastupdate}
    else:
        now = int(time.time())
        extra = {"startdate": now - (days if days is not None else DEFAULT_DAYS) * 86400, "enddate": now}
    count = 0
    for grp in _fetch_measure_pages(access_token, **extra):
        values = body_comp_values(grp)
        if not values:
            continue
        ts = datetime.fromtimestamp(grp["date"], tz=timezone.utc)
        upsert_body_comp(session, SOURCE, str(grp.get("grpid", grp["date"])), ts=ts, **values)
        count += 1
    return count


def configured() -> bool:
    return bool(settings.withings_client_id and settings.withings_client_secret and settings.withings_redirect_uri)


def revoke(session: Session) -> bool:
    """Ends Catch's grant at Withings (`action=revoke`, signed like requesttoken; the access and refresh tokens die with it). Needs the
    Withings `userid` saved at connect time. Live-checked: a correctly signed revoke answers status 0."""
    row = connections.get(session, SOURCE)
    if row is None or not row.account_id or not configured():
        return False
    nonce = _get_nonce()
    resp = _post(
        OAUTH_URL,
        data={
            "action": "revoke",
            "client_id": settings.withings_client_id,
            "nonce": nonce,
            "signature": _sign("revoke", settings.withings_client_id, nonce),
            "userid": row.account_id,
        },
    )
    _check_status(resp.json(), "revoke")
    return True


def disconnect(session: Session) -> dict:
    """Revoke at Withings (best effort), then forget Catch's tokens. Imported measurements are never deleted."""
    revoked = False
    try:
        revoked = revoke(session)
    except Exception as exc:  # noqa: BLE001 — a failed revoke must not keep the user connected
        logger.warning("withings revoke failed: %s", type(exc).__name__)
        session.rollback()
    return {"revoked": revoked, "was_connected": connections.delete(session, SOURCE)}


_CHECK_CODE = "catch-config-check"


def check_app(redirect_uri: str | None = None) -> dict:
    """Operator probe of this server's Withings app — never a user's data. A signed getnonce proves the client id + secret; a token
    request with a made-up code then tells a registered callback ("invalid code") from an unregistered one ("invalid redirect_uri").
    Booleans only."""
    out: dict = {"configured": configured(), "credentials_ok": None, "redirect_uri_registered": None, "error": None}
    if not out["configured"]:
        return out
    try:
        nonce = _get_nonce()
        out["credentials_ok"] = True
        resp = _post(
            OAUTH_URL,
            data={
                "action": "requesttoken",
                "client_id": settings.withings_client_id,
                "grant_type": "authorization_code",
                "nonce": nonce,
                "signature": _sign("requesttoken", settings.withings_client_id, nonce),
                "code": _CHECK_CODE,
                "redirect_uri": redirect_uri or settings.withings_redirect_uri,
            },
        )
        error = str(resp.json().get("error") or "").lower()
        out["redirect_uri_registered"] = False if "redirect_uri" in error else (True if "code" in error else None)
    except WithingsAppMisconfigured:
        out["credentials_ok"] = False
    except ProviderRateLimited:
        out["error"] = "rate_limited"
    except ProviderError:
        out["error"] = "unreachable"
    return out
