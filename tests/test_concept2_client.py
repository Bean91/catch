# Concept2 fixtures here are synthetic, built from the documented request/response examples
# at https://log.concept2.com/developers/documentation/ (pulled 2026-10-31) — the real account
# behind CONCEPT2_ACCESS_TOKEN has zero logged results right now (confirmed live: GET
# /api/users/me/results returned total=0), so there's nothing to record a fixture from yet.
# The live probe did confirm auth works and the /api/users/me profile shape (used for
# _seed_max_hr below). No live network calls in this file.
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlmodel import select

from catch.analytics.erg_math import watts_from_pace
from catch.core.config import settings as real_settings
from catch.core.models import Activity, Stroke
from catch.core.settings_store import get_settings, update_settings
from catch.sync import concept2_client
from conftest import load_fixture

FAKE_SETTINGS = dataclasses.replace(real_settings, concept2_access_token="test-token")


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/users/me":
            return httpx.Response(200, json=load_fixture("concept2", "profile.json"))
        if path == "/api/users/me/results":
            page = request.url.params.get("page", "1")
            fixture = "results_list_page1.json" if page == "1" else "results_list_page2.json"
            return httpx.Response(200, json=load_fixture("concept2", fixture))
        if path.startswith("/api/users/me/results/"):
            result_id = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=load_fixture("concept2", f"result_{result_id}_detail.json"))
        raise AssertionError(f"unexpected path {path}")

    return httpx.MockTransport(handler)


def _http() -> httpx.Client:
    return httpx.Client(base_url=concept2_client.BASE_URL, headers=concept2_client._headers(), transport=_mock_transport())


def test_sync_upserts_activities_with_unit_conversions(monkeypatch, session):
    monkeypatch.setattr(concept2_client, "settings", FAKE_SETTINGS)

    result = concept2_client.sync(session, http=_http())
    assert result["results"] == 3

    rows = session.exec(select(Activity).where(Activity.source == "concept2")).all()
    assert len(rows) == 3

    a101 = next(r for r in rows if r.external_id == "101")
    assert a101.workout_type == "JustRow"
    assert a101.drag_factor == 128
    assert a101.stroke_rate == 28
    assert a101.avg_power == pytest.approx(3600 * 60 / 1200)  # wattminutes_total -> avg watts
    assert a101.avg_hr == 150
    assert a101.max_hr == 165
    assert a101.duration == pytest.approx(1200.0)

    # date_utc="2026-10-20" is null; local date "07:15:00" in America/New_York, end-of-workout.
    expected_end = datetime(2026, 10, 20, 7, 15, 0, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    assert a101.start == expected_end - timedelta(seconds=1200)

    strokes = session.exec(select(Stroke).where(Stroke.activity_id == a101.id).order_by(Stroke.seq)).all()
    assert len(strokes) == 4
    first = strokes[0]
    assert first.t == pytest.approx(30.0)
    assert first.distance == pytest.approx(83.3)
    assert first.pace_500m == pytest.approx(105.0)
    assert first.watts == pytest.approx(watts_from_pace(105.0))
    assert first.stroke_rate == 28
    assert first.hr == 140


def test_sync_uses_date_utc_when_present(monkeypatch, session):
    monkeypatch.setattr(concept2_client, "settings", FAKE_SETTINGS)
    concept2_client.sync(session, http=_http())

    a102 = session.exec(select(Activity).where(Activity.external_id == "102")).first()
    # date_utc is given directly; timezone is null and must be ignored in favour of it.
    expected_end = datetime(2026, 10, 22, 10, 0, 0, tzinfo=timezone.utc)
    assert a102.start == expected_end - timedelta(seconds=420 + 180)
    assert a102.duration == pytest.approx(600.0)


def test_sync_detects_interval_resets(monkeypatch, session):
    monkeypatch.setattr(concept2_client, "settings", FAKE_SETTINGS)
    concept2_client.sync(session, http=_http())

    a102 = session.exec(select(Activity).where(Activity.external_id == "102")).first()
    strokes = session.exec(select(Stroke).where(Stroke.activity_id == a102.id).order_by(Stroke.seq)).all()
    assert [s.seq for s in strokes] == [0, 1, 2, 3, 4, 5]
    assert [s.interval_index for s in strokes] == [0, 0, 0, 1, 1, 1]


def test_sync_is_idempotent(monkeypatch, session):
    monkeypatch.setattr(concept2_client, "settings", FAKE_SETTINGS)
    concept2_client.sync(session, http=_http())
    concept2_client.sync(session, http=_http())

    activities = session.exec(select(Activity).where(Activity.source == "concept2")).all()
    assert len(activities) == 3
    a101 = next(a for a in activities if a.external_id == "101")
    strokes = session.exec(select(Stroke).where(Stroke.activity_id == a101.id)).all()
    assert len(strokes) == 4


def test_result_without_heart_rate_links_to_garmin_and_inherits_hr(monkeypatch, session):
    monkeypatch.setattr(concept2_client, "settings", FAKE_SETTINGS)

    garmin_row = Activity(
        source="garmin",
        external_id="g1",
        type="indoor_rowing",
        start=datetime(2026, 10, 25, 7, 53, 0, tzinfo=timezone.utc),
        duration=480.0,
        avg_hr=158,
        max_hr=172,
    )
    session.add(garmin_row)
    session.commit()

    concept2_client.sync(session, http=_http())

    a103 = session.exec(select(Activity).where(Activity.external_id == "103")).first()
    assert a103.avg_hr == 158
    assert a103.max_hr == 172
    assert a103.linked_activity_id == garmin_row.id

    session.refresh(garmin_row)
    assert garmin_row.linked_activity_id == a103.id

    stroke = session.exec(select(Stroke).where(Stroke.activity_id == a103.id)).first()
    assert stroke.hr is None  # Concept2's hr=0 (absent) must not become a fake zero HR


def test_sync_seeds_max_hr_from_profile_when_unset(monkeypatch, session):
    monkeypatch.setattr(concept2_client, "settings", FAKE_SETTINGS)
    assert get_settings(session)["max_hr"] is None

    concept2_client.sync(session, http=_http())

    assert get_settings(session)["max_hr"] == 194


def test_sync_does_not_overwrite_a_configured_max_hr(monkeypatch, session):
    monkeypatch.setattr(concept2_client, "settings", FAKE_SETTINGS)
    update_settings(session, {"max_hr": 180})

    concept2_client.sync(session, http=_http())

    assert get_settings(session)["max_hr"] == 180


def test_missing_token_raises_clear_error(monkeypatch, session):
    monkeypatch.setattr(concept2_client, "settings", dataclasses.replace(real_settings, concept2_access_token=""))
    with pytest.raises(concept2_client.Concept2AuthError, match="CONCEPT2_ACCESS_TOKEN"):
        concept2_client.sync(session)
