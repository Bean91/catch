from __future__ import annotations

import base64
import dataclasses
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlmodel import select

from catch.core.config import settings as real_settings
from catch.core.models import Activity, DailyWellness, OAuthToken
from catch.sync.garmin_client import GarminAuthError, GarminClient
from conftest import load_fixture


def _fake_jwt(exp_in_seconds: int = 86400) -> str:
    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    header = b64({"alg": "RS256", "typ": "JWT"})
    now = int(datetime.now(timezone.utc).timestamp())
    payload = b64({"exp": now + exp_in_seconds, "iat": now})
    return f"{header}.{payload}.fakesignature"


def test_token_exchange_parses_raw_jwt_body(monkeypatch, session):
    jwt = _fake_jwt()

    def fake_post(url, headers=None, timeout=None):
        assert headers["Authorization"].startswith("ApiKey ")
        return httpx.Response(
            200, text=jwt, headers={"content-type": "text/plain"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr("catch.sync.garmin_client.httpx.post", fake_post)
    monkeypatch.setattr(
        "catch.sync.garmin_client.settings", dataclasses.replace(real_settings, garmin_api_key="fake-key")
    )

    client = GarminClient(session)
    token = client._exchange_token()
    assert token == jwt

    row = session.get(OAuthToken, "garmin")
    assert row is not None
    assert row.expires_at > datetime.now(timezone.utc) + timedelta(hours=23)


def test_token_exchange_401_raises_clear_error(monkeypatch, session):
    def fake_post(url, headers=None, timeout=None):
        return httpx.Response(401, text="unauthorized", request=httpx.Request("POST", url))

    monkeypatch.setattr("catch.sync.garmin_client.httpx.post", fake_post)
    monkeypatch.setattr(
        "catch.sync.garmin_client.settings", dataclasses.replace(real_settings, garmin_api_key="fake-key")
    )

    client = GarminClient(session)
    with pytest.raises(GarminAuthError, match="create a new one"):
        client._exchange_token()


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sleep-service/sleep/dailySleepSummariesByDate":
            return httpx.Response(200, json=load_fixture("garmin", "sleep_range.json"))
        if path.startswith("/hrv-service/hrv/daily/"):
            return httpx.Response(200, json=load_fixture("garmin", "hrv_range.json"))
        if path == "/usersummary-service/v2/dailysummaries":
            return httpx.Response(200, json=load_fixture("garmin", "usersummary_range.json"))
        if path == "/activitylist-service/activities/search/activities":
            start = int(request.url.params.get("start", "0"))
            page = load_fixture("garmin", "activities_list.json") if start == 0 else []
            return httpx.Response(200, json=page)
        if path.startswith("/download-service/files/activity/"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("activity.fit", b"\x0efake-fit-bytes")
            return httpx.Response(200, content=buf.getvalue(), headers={"content-type": "application/x-zip-compressed"})
        raise AssertionError(f"unexpected path {path}")

    return httpx.MockTransport(handler)


def _client_with_cached_token(session) -> GarminClient:
    from catch.core import security

    row = OAuthToken(
        source="garmin",
        access_token_enc=security.encrypt(_fake_jwt()),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
    )
    session.add(row)
    session.commit()
    http = httpx.Client(base_url="https://personal.connectapi.garmin.com", transport=_mock_transport())
    return GarminClient(session, http=http)


def test_sync_health_merges_fields_from_multiple_endpoints(session):
    client = _client_with_cached_token(session)
    start, end = date(2026, 10, 17), date(2026, 10, 19)

    n = client.sync_health(start, end)
    assert n > 0

    row = session.get(DailyWellness, date(2026, 10, 17))
    assert row is not None
    assert row.sleep_seconds is not None
    assert row.hrv_rmssd is not None
    assert row.resting_hr is not None
    assert row.stress is not None
    assert row.body_battery is not None
    assert row.spo2 is not None
    assert row.respiration is not None
    assert row.sleep_score == 92


def test_sync_activities_upserts_and_downloads_fit(session, tmp_path):
    client = _client_with_cached_token(session)
    start, end = date(2026, 10, 1), date(2026, 10, 31)

    count = client.sync_activities(start, end, tmp_path)
    assert count == 2

    rows = session.exec(select(Activity)).all()
    assert len(rows) == 2
    assert all(r.fit_path and r.fit_path.endswith(".fit") for r in rows)
    assert all(r.type for r in rows)

    # Re-sync must not duplicate rows, and must skip re-downloading an existing fit file.
    count2 = client.sync_activities(start, end, tmp_path)
    assert count2 == 2
    assert len(session.exec(select(Activity)).all()) == 2
