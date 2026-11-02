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
        if path.startswith("/weight-service/weight/range/"):
            return httpx.Response(200, json=load_fixture("garmin", "weight_range.json"))
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


def test_sync_weight_converts_grams_to_kg(session):
    """docs/garmin-endpoints.md: the real `/weight-service/weight/range` response reports
    `weight` in grams despite the OpenAPI schema's own "kilograms" description — confirmed
    against this account's real data (2026-11-02)."""
    from catch.core.models import BodyComp

    client = _client_with_cached_token(session)
    n = client.sync_weight(date(2026, 10, 17), date(2026, 10, 19))
    assert n == 2

    rows = session.exec(select(BodyComp).where(BodyComp.source == "garmin")).all()
    by_date = {r.ts.date(): r for r in rows}
    assert by_date[date(2026, 10, 17)].weight_kg == pytest.approx(75.3)
    assert by_date[date(2026, 10, 17)].fat_pct == 18.5
    assert by_date[date(2026, 10, 18)].weight_kg == pytest.approx(75.1)
    # muscleMass/boneMass/bodyWater are never mapped (see docs/garmin-endpoints.md) — no live
    # non-null value exists to confirm their unit, so they stay None rather than guess.
    assert by_date[date(2026, 10, 18)].muscle_kg is None


def test_peloton_pushed_activity_forced_to_cycling_indoor_regardless_of_garmin_type(session, monkeypatch, tmp_path):
    """Task Part B.2: map a Peloton-pushed ride to cycling (indoor) even if Garmin typed the
    import as something else — no real Peloton-pushed activity exists in this account to
    confirm what typeKey Garmin assigns it (docs/peloton.md), so sport_family can't be
    trusted from the summary alone once origin turns out to be Peloton."""
    from catch.sync.fit_parse import FitSamples

    fit_path = tmp_path / "fake.fit"
    fit_path.write_bytes(b"not a real fit file")

    fake_samples = FitSamples(
        start=datetime(2026, 6, 1, 12, tzinfo=timezone.utc),
        duration_s=1800.0,
        hr=[140.0] * 1800,
        power=[180.0] * 1800,
        cadence=[85.0] * 1800,
        is_peloton_like=True,
        hr_source_type="wrist",
    )
    monkeypatch.setattr("catch.sync.garmin_client.parse_fit", lambda path: fake_samples)

    client = GarminClient(session)
    row = Activity(source="garmin", external_id="pel1", type="other", sport_family="other", fit_path=str(fit_path), start=fake_samples.start, duration=1800.0)
    session.add(row)
    session.commit()

    client._ingest_fit_samples(row)
    session.refresh(row)
    assert row.origin == "peloton"
    assert row.sport_family == "cycling"


def test_peloton_and_watch_cycling_merge_despite_mismatched_garmin_types(session, monkeypatch, tmp_path):
    """Even if Garmin typed the Peloton import as outdoor "cycling" (never confirmed live —
    see docs/peloton.md) while the watch's own recording is "indoor_cycling", the two must
    still be eligible to merge — the matching engine's indoor/outdoor hard block must see
    both as indoor once origin=="peloton" forces it."""
    from catch.sync.fit_parse import FitSamples
    from catch.sync.matching import run_matching

    start = datetime(2026, 6, 2, 7, tzinfo=timezone.utc)
    watch = Activity(source="garmin", external_id="watch2", type="indoor_cycling", start=start, duration=1800.0, avg_hr=140)
    peloton_path = tmp_path / "peloton.fit"
    peloton_path.write_bytes(b"not a real fit file")
    peloton = Activity(
        source="garmin", external_id="pel2", type="cycling", start=start + timedelta(seconds=20), duration=1800.0,
        fit_path=str(peloton_path),
    )
    session.add(watch)
    session.add(peloton)
    session.commit()

    fake_samples = FitSamples(start=start, duration_s=1800.0, hr=[], power=[180.0] * 1800, cadence=[85.0] * 1800, is_peloton_like=True)
    monkeypatch.setattr("catch.sync.garmin_client.parse_fit", lambda path: fake_samples)
    client = GarminClient(session)
    client._ingest_fit_samples(peloton)

    run_matching(session)
    session.refresh(watch)
    session.refresh(peloton)
    assert watch.canonical_id == peloton.canonical_id


def test_a_single_fit_download_failure_does_not_abort_the_rest_of_the_sync(session, tmp_path):
    """Real bug found live (2026-11-02): a 429 from Garmin's download-service on one activity
    used to raise out of sync_activities entirely, discarding every later activity in that
    call (and, in a multi-window backfill, every later window too)."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/activitylist-service/activities/search/activities":
            start = int(request.url.params.get("start", "0"))
            page = load_fixture("garmin", "activities_list.json") if start == 0 else []
            return httpx.Response(200, json=page)
        if path == "/download-service/files/activity/24918902966":
            return httpx.Response(429, text="Too Many Requests")
        if path.startswith("/download-service/files/activity/"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("activity.fit", b"\x0efake-fit-bytes")
            return httpx.Response(200, content=buf.getvalue(), headers={"content-type": "application/x-zip-compressed"})
        raise AssertionError(f"unexpected path {path}")

    http = httpx.Client(base_url="https://personal.connectapi.garmin.com", transport=httpx.MockTransport(handler))
    client = GarminClient(session, http=http)
    from catch.core import security

    session.add(
        OAuthToken(source="garmin", access_token_enc=security.encrypt(_fake_jwt()), expires_at=datetime.now(timezone.utc) + timedelta(hours=12))
    )
    session.commit()

    count = client.sync_activities(date(2026, 10, 1), date(2026, 10, 31), tmp_path)
    assert count == 2  # both activities upserted despite the first's FIT download failing

    rows = {r.external_id: r for r in session.exec(select(Activity)).all()}
    assert rows["24918902966"].fit_path is None  # left unset so a later sync retries it
    assert rows["24910202387"].fit_path is not None
