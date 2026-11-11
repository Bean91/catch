from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from catch.sync.fit_parse import parse_fit_track
from tests.test_fit_parse import FakeDataMessage, _patch_fitdecode

T0 = datetime(2026, 10, 30, 20, 37, 42, tzinfo=timezone.utc)


def semi(deg: float) -> int:
    return round(deg * 2**31 / 180)


def rec(offset_s, lat=None, lon=None, **extra):
    fields = {"timestamp": T0 + timedelta(seconds=offset_s), **extra}
    if lat is not None:
        fields["position_lat"] = semi(lat)
        fields["position_long"] = semi(lon)
    return FakeDataMessage("record", fields)


def _file(tmp_path):
    p = tmp_path / "x.fit"
    p.write_bytes(b"fitdecode is faked")
    return p


def test_semicircles_convert_to_degrees(monkeypatch, tmp_path):
    assert semi(90.0) == 2**30  # the hand-checked anchor: 2**30 semicircles is exactly 90 degrees
    _patch_fitdecode(monkeypatch, [rec(0, 45.0, -73.0), rec(5, 45.001, -73.0)])
    t = parse_fit_track(_file(tmp_path))
    assert t.lat[0] == pytest.approx(45.0, abs=1e-6)
    assert t.lon[0] == pytest.approx(-73.0, abs=1e-6)
    assert t.lat[1] == pytest.approx(45.001, abs=1e-6)


def test_time_origin_is_the_first_record_even_if_it_has_no_fix(monkeypatch, tmp_path):
    _patch_fitdecode(monkeypatch, [rec(0, heart_rate=90), rec(7, 45.0, -73.0), rec(12, 45.0001, -73.0)])
    t = parse_fit_track(_file(tmp_path))
    assert t.start == T0
    assert t.n_records == 3
    assert t.t == [7.0, 12.0]  # same origin ActivitySamples uses, so elapsed_s lines up


def test_prefers_enhanced_fields_and_reads_optional_ones(monkeypatch, tmp_path):
    frames = [
        rec(0, 45.0, -73.0, enhanced_speed=2.5, speed=1.0, distance=0.0, heart_rate=120, gps_accuracy=4),
        rec(5, 45.0, -73.0, speed=3.0, distance=12.5, enhanced_altitude=30.2),
    ]
    _patch_fitdecode(monkeypatch, frames)
    t = parse_fit_track(_file(tmp_path))
    assert t.speed == [2.5, 3.0]
    assert t.dist == [0.0, 12.5]
    assert t.hr == [120.0, None]
    assert t.acc == [4.0, None]
    assert t.alt == [None, 30.2]


def test_positionless_file_returns_an_empty_track(monkeypatch, tmp_path):
    _patch_fitdecode(monkeypatch, [rec(0, heart_rate=100), rec(1, heart_rate=101)])
    t = parse_fit_track(_file(tmp_path))
    assert t.n_records == 2 and t.t == []


def test_gps_metadata_messages_are_ignored(monkeypatch, tmp_path):
    frames = [
        FakeDataMessage("gps_metadata", {"enhanced_altitude": 99.0, "enhanced_speed": 9.0}),
        rec(0, 45.0, -73.0),
        rec(5, 45.0001, -73.0),
    ]
    _patch_fitdecode(monkeypatch, frames)
    t = parse_fit_track(_file(tmp_path))
    assert t.alt == [None, None] and t.speed == [None, None]


def test_laps_and_session_fields(monkeypatch, tmp_path):
    frames = [
        rec(0, 45.0, -73.0),
        rec(5, 45.0001, -73.0),
        FakeDataMessage("lap", {"start_time": T0 + timedelta(seconds=2), "total_elapsed_time": 3.0,
                                "total_distance": 11.0, "enhanced_avg_speed": 3.6, "avg_heart_rate": 140}),
        FakeDataMessage("session", {"enhanced_avg_speed": 2.646, "enhanced_max_speed": 5.37,
                                    "total_distance": 7731.9, "total_timer_time": 2501.0}),
    ]
    _patch_fitdecode(monkeypatch, frames)
    t = parse_fit_track(_file(tmp_path))
    assert t.laps == [{"duration_s": 3.0, "distance_m": 11.0, "avg_speed_mps": 3.6, "avg_hr": 140.0,
                       "max_hr": None, "avg_cadence": None, "offset_s": 2.0}]
    assert t.session["max_speed_mps"] == 5.37 and t.session["timer_s"] == 2501.0


def test_missing_file_and_parse_error_return_none(monkeypatch, tmp_path):
    assert parse_fit_track(tmp_path / "nope.fit") is None

    class Boom:
        def __init__(self, path):
            raise RuntimeError("corrupt")

    import types

    monkeypatch.setattr("catch.sync.fit_parse.fitdecode",
                        types.SimpleNamespace(FitReader=Boom, FitDataMessage=FakeDataMessage))
    assert parse_fit_track(_file(tmp_path)) is None
