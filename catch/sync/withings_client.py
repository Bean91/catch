from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Iterator

import httpx
from sqlmodel import Session

from catch.core import security
from catch.core.config import settings
from catch.core.models import OAuthToken
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


class WithingsError(RuntimeError):
    pass


def _check_status(data: dict, action: str) -> None:
    status = data.get("status")
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
    resp = httpx.post(
        SIGNATURE_URL,
        data={"action": "getnonce", "client_id": settings.withings_client_id, "timestamp": timestamp, "signature": signature},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    _check_status(data, "getnonce")
    return data["body"]["nonce"]


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

    resp = httpx.post(OAUTH_URL, data=params, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    _check_status(data, "requesttoken")
    body = data["body"]

    row = session.get(OAuthToken, SOURCE)
    if row is None:
        row = OAuthToken(source=SOURCE, access_token_enc="")
        session.add(row)
    row.access_token_enc = security.encrypt(body["access_token"])
    row.refresh_token_enc = security.encrypt(body["refresh_token"])
    row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(body.get("expires_in", 10800)))
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return body["access_token"]


def exchange_code(session: Session, code: str) -> str:
    return _request_token(session, grant_type="authorization_code", code=code)


def get_access_token(session: Session) -> str:
    row = session.get(OAuthToken, SOURCE)
    if row is None:
        raise WithingsError("No Withings tokens stored — visit /auth/withings/start first")
    if row.expires_at and row.expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return security.decrypt(row.access_token_enc)
    refresh_token = security.decrypt(row.refresh_token_enc)
    return _request_token(session, grant_type="refresh_token", refresh_token=refresh_token)


def _fetch_measure_pages(access_token: str, **extra_params: str) -> Iterator[dict]:
    params = {"action": "getmeas", "meastypes": MEASTYPES, "category": 1, **extra_params}
    offset = None
    while True:
        if offset:
            params["offset"] = offset
        resp = httpx.post(
            MEASURE_URL,
            data=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        _check_status(data, "getmeas")
        body = data.get("body", {})
        for grp in body.get("measuregrps", []):
            yield grp
        if not body.get("more"):
            return
        offset = body.get("offset")


def sync(session: Session, lastupdate: int | None = None, days: int | None = None) -> int:
    access_token = get_access_token(session)
    if days is not None:
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
