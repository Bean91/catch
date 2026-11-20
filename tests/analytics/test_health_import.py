"""Session 30: duplicate detection, validation and sport mapping for Apple Health / Health Connect imports."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from catch.analytics import health_import as h

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("app, ident, connected, expected", [
    ("Garmin Connect", "com.garmin.connect.mobile", {"garmin"}, "garmin"),
    ("Garmin Connect", "com.garmin.connect.mobile", set(), None),  # Garmin not connected: this is the only copy, import it
    ("Health Mate", "com.withings.wiscale2", {"withings"}, "withings"),
    ("WHOOP", "com.whoop.iphone", {"whoop", "garmin"}, "whoop"),
    ("Concept2 Logbook", None, {"concept2"}, "concept2"),
    ("Strava", "com.strava", {"garmin", "withings", "whoop", "concept2"}, None),
    ("Apple Watch", "com.apple.health", {"garmin"}, None),
    (None, None, {"garmin"}, None),
])
def test_a_record_is_a_duplicate_only_of_a_connected_provider(app, ident, connected, expected):
    assert h.duplicate_of(app, ident, connected) == expected


def _w(**kw):
    return {"external_id": "w1", "type": "rowingMachine", "start": "2026-11-19T07:00:00Z", "end": "2026-11-19T07:40:00Z", "distance_m": 8000, "energy_kcal": 500, "avg_hr": 150, "max_hr": 178, "origin_app": "Apple Watch", **kw}


def test_a_good_workout_is_normalised():
    v = h.validate_workout(_w(), now=NOW)
    assert v["duration"] == 2400 and v["distance"] == 8000 and v["type"] == "rowingMachine" and v["origin_app"] == "Apple Watch"
    assert v["start"].tzinfo is not None


@pytest.mark.parametrize("bad", [
    {"external_id": ""}, {"external_id": 5}, {"start": "yesterday"}, {"end": "2026-11-19T06:00:00Z"}, {"end": "2026-11-21T09:00:00Z"},
    {"start": "2026-11-25T07:00:00Z", "end": "2026-11-25T08:00:00Z"}, {"start": "2024-01-01T07:00:00Z", "end": "2024-01-01T08:00:00Z"},
    {"avg_hr": 400}, {"avg_hr": 190, "max_hr": 150}, {"distance_m": -5}, {"distance_m": "far"}, {"energy_kcal": float("nan")}, {"avg_hr": True}, {"origin_app": 12},
])
def test_implausible_or_malformed_workouts_are_refused_without_echoing_the_value(bad):
    with pytest.raises(h.Invalid) as e:
        h.validate_workout(_w(**bad), now=NOW)
    assert "far" not in str(e.value) and "yesterday" not in str(e.value)


def test_sleep_carries_its_stages_and_other_readings_map_to_catch_signals():
    s = h.validate_reading({"category": "sleep", "date": "2026-11-19", "sleep_seconds": 27000, "deep_sleep_seconds": 5400, "rem_sleep_seconds": 6000, "origin_app": "Apple Watch"}, today=date(2026, 11, 20))
    assert s["signal"] == "sleep_seconds" and s["value"] == 27000 and s["meta"] == {"deep_sleep_seconds": 5400.0, "rem_sleep_seconds": 6000.0}
    assert h.validate_reading({"category": "resting_hr", "date": "2026-11-19", "value": 52}, today=date(2026, 11, 20))["signal"] == "resting_hr"
    assert h.validate_reading({"category": "hrv", "date": "2026-11-19", "value": 61}, today=date(2026, 11, 20))["signal"] == "hrv_rmssd"
    assert h.validate_reading({"category": "spo2", "date": "2026-11-19", "value": 97}, today=date(2026, 11, 20))["signal"] == "spo2"


@pytest.mark.parametrize("bad", [
    {"category": "steps", "value": 9000}, {"category": "resting_hr", "value": 5}, {"category": "spo2", "value": 140}, {"category": "sleep", "sleep_seconds": 60},
    {"category": "resting_hr", "value": 50, "date": "2099-01-01"}, {"category": "resting_hr", "value": 50, "date": "not-a-date"}, {"category": "resting_hr", "value": None},
])
def test_bad_readings_are_refused(bad):
    base = {"date": "2026-11-19", **bad}
    with pytest.raises(h.Invalid):
        h.validate_reading(base, today=date(2026, 11, 20))


def test_hrv_is_android_only_because_healthkit_reports_sdnn_not_rmssd():
    assert "hrv" not in h.CATEGORIES_BY_SOURCE["apple_health"] and "hrv" in h.CATEGORIES_BY_SOURCE["health_connect"]
    assert set(h.CATEGORIES_BY_SOURCE["health_connect"]) == set(h.CATEGORIES)


def test_sport_mapping():
    assert h.sport_family("rowingMachine") == "rowing" and h.is_indoor("rowingMachine") is True
    assert h.sport_family("rowing") == "rowing" and h.is_indoor("rowing") is None
    assert h.sport_family("traditionalStrengthTraining") == "strength"
    assert h.sport_family("yoga") == "other" and h.sport_family(None) == "other"
