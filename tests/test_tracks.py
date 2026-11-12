from __future__ import annotations

import json

import pytest
from sqlmodel import select

from catch.core.models import Activity, ActivitySamples, ActivityTrack
from catch.sync.tracks import backfill_tracks, filtered_for, ingest_track, load_raw_track
from tests.test_fit_parse import FakeDataMessage, _patch_fitdecode
from tests.test_fit_track_parse import T0, rec

M_PER_DEG = 111194.93


def rowing_frames(n=101, speed=4.0, dt=5.0, with_hr=True):
    step = speed * dt / M_PER_DEG
    return [
        rec(i * dt, 45.0 + i * step, -73.0, heart_rate=(140 + i % 5) if with_hr else None,
            enhanced_speed=speed, distance=i * speed * dt)
        for i in range(n)
    ]


def make_activity(session, tmp_path, *, type_="rowing_v2", family="rowing", ext="g1", raw=None):
    fit = tmp_path / f"{ext}.fit"
    fit.write_bytes(b"faked")
    a = Activity(source="garmin", external_id=ext, type=type_, start=T0, duration=500.0,
                 sport_family=family, fit_path=str(fit),
                 raw_json=json.dumps(raw or {"distance": 2010.0, "movingDuration": 498.0, "maxSpeed": 4.4,
                                              "averageSpeed": 4.0, "locationName": "Westport"}))
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_ingest_stores_a_roundtrippable_track_and_provider_figures(session, tmp_path, monkeypatch):
    a = make_activity(session, tmp_path)
    _patch_fitdecode(monkeypatch, rowing_frames() + [
        FakeDataMessage("session", {"enhanced_max_speed": 5.0, "total_distance": 1999.0})])
    row = ingest_track(session, a)
    assert row.n_points == 101 and row.n_records == 101
    raw = load_raw_track(row)
    assert raw.lat[0] == pytest.approx(45.0, abs=1e-6)
    assert raw.lat[100] == pytest.approx(45.0 + 2000.0 / M_PER_DEG, abs=1e-6)  # 500 s at 4 m/s due north
    assert raw.t[100] == 500.0
    assert raw.hr[3] == 143.0
    assert raw.speed[0] == 4.0
    prov = json.loads(row.provider_json)
    assert prov["distance_m"] == 2010.0 and prov["moving_s"] == 498.0  # Garmin summary wins over FIT session
    assert prov["max_speed_mps"] == 4.4
    summary = json.loads(row.summary_json)
    assert summary["distance_m"] == pytest.approx(2000.0, abs=1.0)
    assert summary["avg_hr"] == pytest.approx(142.0, abs=0.1)
    assert len(summary["signature"]) == 64  # rowing -> route signature cached
    assert row.alt_blob is None and row.acc_blob is None  # never stored when the device didn't report them


def test_positionless_fit_is_recorded_so_it_is_not_reparsed(session, tmp_path, monkeypatch):
    a = make_activity(session, tmp_path, type_="indoor_rowing", ext="g2")
    _patch_fitdecode(monkeypatch, [rec(0, heart_rate=100), rec(1, heart_rate=101)])
    row = ingest_track(session, a)
    assert row.n_points == 0 and row.n_records == 2 and row.summary_json is None
    assert load_raw_track(row) is None
    monkeypatch.setattr("catch.sync.tracks.parse_fit_track", lambda p: pytest.fail("re-parsed"))
    assert ingest_track(session, a) is row


def test_non_rowing_gps_activity_gets_a_track_but_no_route_signature(session, tmp_path, monkeypatch):
    a = make_activity(session, tmp_path, type_="running", family="running", ext="g3")
    _patch_fitdecode(monkeypatch, rowing_frames(speed=3.0))
    row = ingest_track(session, a)
    assert row.n_points == 101
    assert "signature" not in json.loads(row.summary_json)


def test_missing_fit_file_stores_nothing(session, tmp_path):
    a = make_activity(session, tmp_path, ext="g4")
    (tmp_path / "g4.fit").unlink()
    assert ingest_track(session, a) is None
    assert session.get(ActivityTrack, a.id) is None


def test_ingest_does_not_touch_samples_or_the_activity(session, tmp_path, monkeypatch):
    a = make_activity(session, tmp_path, ext="g5")
    before = a.model_dump()
    _patch_fitdecode(monkeypatch, rowing_frames())
    ingest_track(session, a)
    session.refresh(a)
    assert a.model_dump() == before
    assert session.get(ActivitySamples, a.id) is None


def test_filtered_track_uses_the_sport_ceiling(session, tmp_path, monkeypatch):
    a = make_activity(session, tmp_path, ext="g6")
    _patch_fitdecode(monkeypatch, rowing_frames())
    row = ingest_track(session, a)
    ft = filtered_for(session, a, row)
    assert ft.report["ceiling_mps"] == 10.0


def test_backfill_covers_every_activity_with_a_fit_and_is_idempotent(session, tmp_path, monkeypatch):
    make_activity(session, tmp_path, ext="b1")
    make_activity(session, tmp_path, type_="indoor_rowing", ext="b2")
    no_fit = make_activity(session, tmp_path, ext="b3")
    no_fit.fit_path = None
    session.add(no_fit)
    session.commit()
    _patch_fitdecode(monkeypatch, rowing_frames())
    assert backfill_tracks(session) == {"parsed": 2, "with_gps": 2, "skipped": 0}
    assert len(session.exec(select(ActivityTrack)).all()) == 2
    assert backfill_tracks(session)["parsed"] == 2  # existing rows are returned, not re-parsed
