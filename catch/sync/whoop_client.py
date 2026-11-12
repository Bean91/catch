"""WHOOP v2 developer API: OAuth 2 (authorization code + rotating refresh tokens) and the import
of workouts, sleep, recovery and the wellness signals they carry. Endpoint and field facts are in
docs/whoop-endpoints.md; anything the official docs don't confirm isn't imported.

Refresh tokens rotate: the moment a refresh succeeds the old token is dead, and a second
concurrent refresh fails. So refreshing is serialized behind a process-wide lock, re-reads the
stored token after taking it (another caller may have just refreshed), and commits the new pair
before returning.
"""

from __future__ import annotations

from catch.core import tenant
import json
import threading
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

import httpx
from sqlmodel import Session

from catch.analytics.planning import aware_utc
from catch.analytics.wellness_inputs import pick_main_sleep
from catch.analytics.whoop import kj_to_kcal, parse_instant, parse_offset_minutes, sleep_wake_date
from catch.core import security
from catch.core.config import settings
from catch.core.models import OAuthToken
from catch.core.redact import register_secret
from catch.sync import wellness_readings
from catch.sync.upsert import upsert_activity

SOURCE = "whoop"
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_BASE = "https://api.prod.whoop.com/developer"
SCOPES = "offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement"
PAGE_LIMIT = 25  # the documented maximum
MAX_PAGES = 200  # bound a backfill's memory and request count
_REFRESH_SKEW = timedelta(minutes=5)
_RATE_WAIT_CAP_S = 15.0

_refresh_lock = threading.Lock()


class WhoopError(RuntimeError):
    """Never carries a token, a URL with credentials, or Whoop's response body."""


class WhoopReconnectNeeded(WhoopError):
    """The refresh token was refused (revoked, already rotated, or expired): the user has to
    authorize again. Raised instead of retrying, so a dead token can't loop."""


class WhoopRateLimited(WhoopError):
    pass


def configured() -> bool:
    return bool(settings.whoop_client_id and settings.whoop_client_secret and settings.whoop_redirect_uri)


def authorize_url(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.whoop_client_id,
        "redirect_uri": settings.whoop_redirect_uri,
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def new_state() -> str:
    # Whoop's docs say `state` must be eight characters; 6 random bytes encode to exactly 8.
    import secrets

    return secrets.token_urlsafe(6)


def _http(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), transport=transport)


def _store_tokens(session: Session, body: dict) -> str:
    row = session.get(OAuthToken, tenant.pk(SOURCE))
    if row is None:
        row = OAuthToken(source=SOURCE, access_token_enc="")
        session.add(row)
    row.access_token_enc = security.encrypt(body["access_token"])
    if body.get("refresh_token"):
        row.refresh_token_enc = security.encrypt(body["refresh_token"])
    row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(body.get("expires_in") or 3600))
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    register_secret(body["access_token"])
    register_secret(body.get("refresh_token"))
    return body["access_token"]


def _token_request(form: dict, transport: httpx.BaseTransport | None) -> dict:
    form = {**form, "client_id": settings.whoop_client_id, "client_secret": settings.whoop_client_secret}
    try:
        with _http(transport) as client:
            resp = client.post(TOKEN_URL, data=form, headers={"Accept": "application/json"})
    except httpx.HTTPError:
        raise WhoopError("Couldn't reach Whoop to exchange a token.") from None
    if resp.status_code in (400, 401):
        raise WhoopReconnectNeeded("Whoop refused the token. Reconnect Whoop in Settings.")
    if resp.status_code != 200:
        raise WhoopError(f"Whoop token request failed (HTTP {resp.status_code}).")
    try:
        body = resp.json()
        body["access_token"]
    except (ValueError, KeyError):
        raise WhoopError("Whoop sent a token response Catch couldn't read.") from None
    return body


def exchange_code(session: Session, code: str, transport: httpx.BaseTransport | None = None) -> None:
    body = _token_request(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.whoop_redirect_uri},
        transport,
    )
    _store_tokens(session, body)


def get_access_token(session: Session, transport: httpx.BaseTransport | None = None, *, force: bool = False) -> str:
    row = session.get(OAuthToken, tenant.pk(SOURCE))
    if row is None or not row.refresh_token_enc:
        raise WhoopReconnectNeeded("Whoop isn't connected. Connect it in Settings.")
    if not force and row.expires_at and aware_utc(row.expires_at) > datetime.now(timezone.utc) + _REFRESH_SKEW:
        return security.decrypt(row.access_token_enc)
    with _refresh_lock:
        session.refresh(row)  # another caller may have rotated the token while we waited
        if not force and row.expires_at and aware_utc(row.expires_at) > datetime.now(timezone.utc) + _REFRESH_SKEW:
            return security.decrypt(row.access_token_enc)
        body = _token_request(
            {"grant_type": "refresh_token", "refresh_token": security.decrypt(row.refresh_token_enc), "scope": "offline"},
            transport,
        )
        return _store_tokens(session, body)


class WhoopApi:
    def __init__(self, session: Session, transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self.session = session
        self.transport = transport
        self._sleep = sleep

    def _request(self, method: str, path: str, params: dict | None = None, *, _retried_auth=False, _retried_rate=False) -> httpx.Response:
        token = get_access_token(self.session, self.transport)
        try:
            with _http(self.transport) as client:
                resp = client.request(method, f"{API_BASE}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError:
            raise WhoopError("Couldn't reach Whoop.") from None
        if resp.status_code == 401 and not _retried_auth:
            get_access_token(self.session, self.transport, force=True)
            return self._request(method, path, params, _retried_auth=True, _retried_rate=_retried_rate)
        if resp.status_code == 401:
            raise WhoopReconnectNeeded("Whoop rejected the access token. Reconnect Whoop in Settings.")
        if resp.status_code == 429:
            # `Retry-After` isn't documented; `X-RateLimit-Reset` (seconds until the closest
            # window resets) is. Wait once, briefly; a long wait belongs to the next scheduled sync.
            try:
                wait = float(resp.headers.get("x-ratelimit-reset") or resp.headers.get("retry-after") or 5)
            except ValueError:
                wait = 5.0
            if _retried_rate or wait > _RATE_WAIT_CAP_S:
                raise WhoopRateLimited("Whoop is rate-limiting Catch; the next sync will resume.")
            self._sleep(wait)
            return self._request(method, path, params, _retried_auth=_retried_auth, _retried_rate=True)
        if resp.status_code >= 400:
            raise WhoopError(f"Whoop returned HTTP {resp.status_code} for {path}.")
        return resp

    def get(self, path: str, params: dict | None = None) -> dict:
        try:
            return self._request("GET", path, params).json()
        except ValueError:
            raise WhoopError("Whoop sent a response Catch couldn't read.") from None

    def records(self, path: str, start: datetime, end: datetime | None = None) -> Iterator[dict]:
        params: dict = {"limit": PAGE_LIMIT, "start": start.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
        if end:
            params["end"] = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        for _ in range(MAX_PAGES):
            page = self.get(path, params)
            yield from page.get("records") or []
            token = page.get("next_token")
            if not token:
                return
            params["nextToken"] = token
        raise WhoopError("Whoop returned more pages than Catch will read in one sync.")

    def revoke(self) -> bool:
        try:
            self._request("DELETE", "/v2/user/access")
            return True
        except WhoopError:
            return False


# -- import -----------------------------------------------------------------------------------


def _scored(record: dict) -> dict | None:
    return record.get("score") if record.get("score_state") == "SCORED" and record.get("score") else None


def _milli_to_s(value) -> int | None:
    return int(value) // 1000 if value is not None else None


def _sleep_record(sleep: dict) -> dict | None:
    score = _scored(sleep)
    day = sleep_wake_date(sleep)
    end = parse_instant(sleep.get("end"))
    if score is None or day is None or end is None:
        return None
    stages = score.get("stage_summary") or {}
    light, deep, rem = (stages.get(k) for k in ("total_light_sleep_time_milli", "total_slow_wave_sleep_time_milli", "total_rem_sleep_time_milli"))
    if light is None and deep is None and rem is None:
        return None
    asleep = _milli_to_s(sum(v or 0 for v in (light, deep, rem)))
    offset = parse_offset_minutes(sleep.get("timezone_offset"))
    local_end = end + timedelta(minutes=offset)
    return {
        "id": sleep["id"],
        "day": day,
        "nap": bool(sleep.get("nap")),
        "seconds": asleep,
        "end": end,
        "meta": {
            "deep_sleep_seconds": _milli_to_s(deep),
            "light_sleep_seconds": _milli_to_s(light),
            "rem_sleep_seconds": _milli_to_s(rem),
            "awake_sleep_seconds": _milli_to_s(stages.get("total_awake_time_milli")),
            "wake_time_minutes": local_end.hour * 60 + local_end.minute,
        },
        "respiratory_rate": score.get("respiratory_rate"),
    }


def import_sleep_and_recovery(session: Session, sleeps: list[dict], recoveries: list[dict]) -> set[date]:
    """Record readings for the main (non-nap) sleep of each wake day and the recoveries that
    belong to those sleeps. A recovery is dated by its `sleep_id`'s wake day — never by its
    cycle's start — so the same night from Garmin and Whoop lands on the same date."""
    by_day: dict[date, list[dict]] = {}
    by_id: dict[str, dict] = {}
    for raw in sleeps:
        rec = _sleep_record(raw)
        if rec is None:
            continue
        by_id[rec["id"]] = rec
        by_day.setdefault(rec["day"], []).append(rec)
    touched: set[date] = set()
    main_ids: dict[str, date] = {}
    for day, records in by_day.items():
        main = pick_main_sleep(records)
        if main is None:
            continue
        main_ids[main["id"]] = day
        meta = {k: v for k, v in main["meta"].items() if v is not None}
        wellness_readings.record_reading(session, day, SOURCE, "sleep_seconds", main["seconds"], recorded_at=main["end"], external_id=main["id"], meta=meta, commit=False)
        wellness_readings.record_reading(session, day, SOURCE, "sleep_respiration", main["respiratory_rate"], recorded_at=main["end"], external_id=main["id"], commit=False)
        touched.add(day)
    for raw in recoveries:
        score = _scored(raw)
        sleep_id = raw.get("sleep_id")
        day = main_ids.get(sleep_id)
        if score is None or day is None:
            continue  # unscored, a nap's recovery, or a sleep outside this window
        ref = {"whoop_recovery_score": score.get("recovery_score"), "user_calibrating": score.get("user_calibrating")}  # reference only; never an input
        wellness_readings.record_reading(session, day, SOURCE, "hrv_rmssd", score.get("hrv_rmssd_milli"), external_id=sleep_id, meta=ref, commit=False)
        wellness_readings.record_reading(session, day, SOURCE, "resting_hr", score.get("resting_heart_rate"), external_id=sleep_id, commit=False)
        wellness_readings.record_reading(session, day, SOURCE, "spo2", score.get("spo2_percentage"), external_id=sleep_id, commit=False)
        wellness_readings.record_reading(session, day, SOURCE, "skin_temp_c", score.get("skin_temp_celsius"), external_id=sleep_id, commit=False)
    session.commit()
    return touched


def import_workouts(session: Session, workouts: list[dict]) -> int:
    n = 0
    for w in workouts:
        score = _scored(w)
        start, end = parse_instant(w.get("start")), parse_instant(w.get("end"))
        if score is None or start is None or end is None or not w.get("id"):
            continue
        kcal = kj_to_kcal(score.get("kilojoule"))
        upsert_activity(
            session,
            SOURCE,
            str(w["id"]),
            type=(w.get("sport_name") or "").strip().lower() or None,
            start=start,
            duration=(end - start).total_seconds(),
            distance=score.get("distance_meter"),
            avg_hr=score.get("average_heart_rate"),
            max_hr=score.get("max_heart_rate"),
            calories=kcal,
            hr_source_type="wrist",
            raw_json=json.dumps(w),
        )
        n += 1
    return n


def sync(session: Session, days: int = 3, transport: httpx.BaseTransport | None = None, sleep=time.sleep, now: datetime | None = None) -> int:
    api = WhoopApi(session, transport, sleep)
    end = now or datetime.now(timezone.utc)
    # Pad the window by a day: the sleep that ends on the first day started the evening before.
    start = end - timedelta(days=days + 1)
    sleeps = list(api.records("/v2/activity/sleep", start))
    recoveries = list(api.records("/v2/recovery", start))
    workouts = list(api.records("/v2/activity/workout", start))
    touched = import_sleep_and_recovery(session, sleeps, recoveries)
    wellness_readings.resolve_days(session, touched)
    return len(touched) + import_workouts(session, workouts)


def disconnect(session: Session, transport: httpx.BaseTransport | None = None) -> dict:
    """Revokes Catch's access at Whoop (best effort) and forgets the tokens. Imported data stays."""
    row = session.get(OAuthToken, tenant.pk(SOURCE))
    if row is None:
        return {"revoked": False, "was_connected": False}
    revoked = False
    try:
        revoked = WhoopApi(session, transport).revoke()
    except WhoopError:
        pass
    session.delete(session.get(OAuthToken, tenant.pk(SOURCE)))
    from catch.core.models import SyncState

    state_row = session.get(SyncState, tenant.pk(SOURCE))
    if state_row is not None:
        session.delete(state_row)  # a disconnected source must not be reported as a stale sync
    session.commit()
    return {"revoked": revoked, "was_connected": True}


def check(session: Session, transport: httpx.BaseTransport | None = None) -> dict:
    """The manual connection test: touches each scope's endpoint once and reports counts only —
    never tokens, names or e-mail addresses."""
    api = WhoopApi(session, transport)
    profile = api.get("/v2/user/profile/basic")
    out = {"connected": True, "user_id_present": profile.get("user_id") is not None}
    for label, path in (("recovery", "/v2/recovery"), ("sleep", "/v2/activity/sleep"), ("workout", "/v2/activity/workout"), ("cycle", "/v2/cycle")):
        page = api.get(path, {"limit": 1})
        out[label] = {"ok": True, "has_records": bool(page.get("records"))}
    row = session.get(OAuthToken, tenant.pk(SOURCE))
    out["token_expires_at"] = aware_utc(row.expires_at).isoformat() if row and row.expires_at else None
    return out
