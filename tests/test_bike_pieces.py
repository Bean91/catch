"""Session 33, Part C: bike pieces next to rowing erg pieces — saved, edited and listed with the right unit, and kept out of every
rowing-only reader (test center, PBs, the 2k estimate, leaderboards, Concept2 absorb, fast-start flags, the power overlay)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.coach import tools
from catch.core.models import Activity, CanonicalActivity, Piece
from catch.sync import erg_test, rowing_predict
from catch.sync import piece as piece_sync
from catch.sync.training_intelligence import _fast_start_flags
from conftest import TEST_PASSWORD

T0 = datetime(2026, 7, 1, 7, tzinfo=timezone.utc)
BIKE_SPLITS = [
    {"split_index": 1, "distance_m": 1000.0, "split_s": 100.0, "rate": 92.0, "watts": 260.0, "hr": None},
    {"split_index": 2, "distance_m": 2000.0, "split_s": 102.0, "rate": 94.0, "watts": 250.0, "hr": None},
]
ROW_SPLITS = [
    {"split_index": 1, "distance_m": 500.0, "split_s": 96.8, "rate": 32.0, "watts": None, "hr": None},
    {"split_index": 2, "distance_m": 1000.0, "split_s": 98.9, "rate": 30.0, "watts": None, "hr": None},
    {"split_index": 3, "distance_m": 1500.0, "split_s": 99.0, "rate": 31.0, "watts": None, "hr": None},
    {"split_index": 4, "distance_m": 2000.0, "split_s": 97.7, "rate": 32.0, "watts": None, "hr": None},
]


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _activity(session, sport: str, ext: str, start: datetime = T0, source: str = "garmin", type_: str | None = None) -> Activity:
    a = Activity(source=source, external_id=ext, type=type_ or ("indoor_cycling" if sport == "cycling" else "indoor_rowing"), start=start, duration=3600.0, sport_family=sport)
    session.add(a)
    session.commit()
    c = CanonicalActivity(sport_family=sport, start=start, duration=3600.0)
    session.add(c)
    session.commit()
    a.canonical_id = c.id
    session.add(a)
    session.commit()
    return a


def test_a_cycling_workouts_piece_defaults_to_bike_with_pace_per_1000m(client, session):
    bike = _activity(session, "cycling", "b1")
    _login(client)
    resp = client.post(f"/api/activities/{bike.canonical_id}/pieces", json={"piece_type": "2000m", "splits": BIKE_SPLITS})
    assert resp.status_code == 200, resp.text
    piece = resp.json()["piece"]
    assert piece["modality"] == "bike" and piece["split_unit_m"] == 1000.0
    assert piece["avg_split_s"] == pytest.approx(101.0)  # 202 s over 2 km, per 1000 m — not 50.5 per 500 m
    assert piece["avg_watts"] == pytest.approx(255.0)  # typed watts kept, never derived from pace


def test_rowing_stays_the_default_and_a_bike_piece_can_sit_on_any_workout(client, session):
    row = _activity(session, "rowing", "r1")
    _login(client)
    rowing = client.post(f"/api/activities/{row.canonical_id}/pieces", json={"piece_type": "2000m", "splits": ROW_SPLITS}).json()["piece"]
    assert rowing["modality"] == "rowing_erg" and rowing["split_unit_m"] == 500.0
    assert rowing["avg_split_s"] == pytest.approx(98.1)
    bike = client.post(f"/api/activities/{row.canonical_id}/pieces", json={"piece_type": "2000m", "splits": BIKE_SPLITS, "modality": "bike"}).json()["piece"]
    assert bike["modality"] == "bike"


def test_rowing_only_types_and_unknown_modalities_are_refused(client, session):
    bike = _activity(session, "cycling", "b1")
    _login(client)
    capped = client.post(f"/api/activities/{bike.canonical_id}/pieces", json={"piece_type": "30min_r20", "splits": [], "duration_s": 1800})
    assert capped.status_code == 422 and "rowing-only" in capped.json()["detail"]
    other = client.post(f"/api/activities/{bike.canonical_id}/pieces", json={"piece_type": "2000m", "splits": BIKE_SPLITS, "modality": "skierg"})
    assert other.status_code == 422


def test_bike_template_rows_are_1000m(client, session):
    bike = _activity(session, "cycling", "b1")
    _login(client)
    rows = client.get(f"/api/activities/{bike.canonical_id}/pieces/template", params={"type": "5000m"}).json()["splits"]
    assert [r["distance_m"] for r in rows] == [1000, 2000, 3000, 4000, 5000]


def test_editing_the_modality_restates_the_pace_and_survives_a_reload(client, session):
    row = _activity(session, "rowing", "r1")
    _login(client)
    piece = client.post(f"/api/activities/{row.canonical_id}/pieces", json={"piece_type": "2000m", "splits": ROW_SPLITS}).json()["piece"]
    resp = client.patch(f"/api/pieces/{piece['id']}", json={"modality": "bike"})
    assert resp.status_code == 200, resp.text
    reloaded = client.get(f"/api/pieces/{piece['id']}").json()
    assert reloaded["modality"] == "bike" and reloaded["avg_split_s"] == pytest.approx(196.2)


def test_bike_intervals_are_summarised_per_1000m(client, session):
    bike = _activity(session, "cycling", "b1")
    _login(client)
    rows = [
        {"target_type": "distance", "work_distance_m": 1000, "work_duration_s": 100, "rest_duration_s": 60, "avg_rate": 90},
        {"target_type": "distance", "work_distance_m": 1000, "work_duration_s": 104, "avg_rate": 92},
    ]
    resp = client.post(f"/api/activities/{bike.canonical_id}/pieces", json={"piece_type": "custom", "intervals": rows})
    piece = resp.json()["piece"]
    assert piece["modality"] == "bike" and piece["has_intervals"]
    assert piece["interval_summary"]["avg_split_s"] == pytest.approx(102.0)
    assert piece["intervals"][0]["split_s"] == pytest.approx(100.0)
    assert resp.json()["validation"]["ok"]  # 90 rpm is a cadence, not an implausible stroke rate


def test_bike_pieces_never_reach_rowing_readers(client, session):
    row = _activity(session, "rowing", "r1")
    bike = _activity(session, "cycling", "b1", start=T0 + timedelta(days=1))
    _login(client)
    client.post(f"/api/activities/{row.canonical_id}/pieces", json={"piece_type": "2000m", "splits": ROW_SPLITS})
    client.post(f"/api/activities/{bike.canonical_id}/pieces", json={"piece_type": "2000m", "splits": BIKE_SPLITS})

    assert [t["modality"] for t in erg_test.list_tests(session)] == ["rowing_erg"]
    assert all(t["modality"] == "rowing_erg" for t in client.get("/api/tests").json()["tests"])
    assert [p["modality"] for p in client.get("/api/tests/bike-pieces").json()["pieces"]] == ["bike"]
    assert len(piece_sync.piece_pb_candidates(session)) == 1
    declared = [e for e in rowing_predict.evidence(session, DEFAULT_SETTINGS) if e.get("effort") == "declared"]
    assert len(declared) == 1 and declared[0]["duration_s"] == pytest.approx(392.4)
    assert len(_fast_start_flags(session)) <= 1  # only the rowing piece is analysed for a fast start


def test_a_bike_piece_does_not_absorb_a_bikeerg_result(session):
    bike = _activity(session, "cycling", "b1")
    piece, _ = piece_sync.create_piece(session, bike.canonical_id, "2000m", [dict(r) for r in BIKE_SPLITS], modality="bike")
    c2 = _activity(session, "cycling", "c2-bike", source="concept2", type_="bike")
    c2.distance, c2.duration = 2000.0, 202.0
    session.add(c2)
    session.commit()
    assert piece_sync.absorb_concept2_piece_results(session) == 0
    session.refresh(piece)
    assert piece.concept2_activity_id is None


def test_a_rowing_piece_does_not_overlay_watts_onto_a_cycling_session(session):
    bike = _activity(session, "cycling", "b1")
    piece, _ = piece_sync.create_piece(session, bike.canonical_id, "2000m", [dict(r, watts=300.0) for r in ROW_SPLITS], modality="rowing_erg", force=True)
    piece.window_activity_id, piece.window_start_s, piece.window_end_s = bike.id, 0, 392
    session.add(piece)
    session.commit()
    members = session.exec(select(Activity).where(Activity.canonical_id == bike.canonical_id)).all()
    member, samples = piece_sync.power_member_and_samples(session, bike.canonical_id, members, None, None, "cycling")
    assert member is None and samples is None
    member, samples = piece_sync.power_member_and_samples(session, bike.canonical_id, members, None, None, "rowing")
    assert member is not None  # the same piece on a rowing session still refines it


def test_coach_add_piece_carries_the_modality_and_unit(session):
    bike = _activity(session, "cycling", "b1")
    preview = tools.call_tool(session, "add_piece", {"piece_type": "2000m", "canonical_id": bike.canonical_id, "splits": BIKE_SPLITS})
    assert preview["saved"] is False and preview["modality"] == "bike" and preview["split_unit_m"] == 1000.0
    saved = tools.call_tool(session, "add_piece", {"piece_type": "2000m", "canonical_id": bike.canonical_id, "splits": BIKE_SPLITS, "confirm": True})
    assert saved["piece"]["modality"] == "bike"
    with pytest.raises(Exception):
        tools.call_tool(session, "add_piece", {"piece_type": "30min_r20", "canonical_id": bike.canonical_id, "text": "30:00.0", "confirm": True})


def test_a_piece_row_without_a_modality_reads_as_rowing(session):
    row = _activity(session, "rowing", "r1")
    p = Piece(canonical_id=row.canonical_id, piece_type="2000m", distance_m=2000.0, duration_s=392.4)
    session.add(p)
    session.commit()
    assert p.modality == "rowing_erg"
    assert piece_sync.piece_dict(p)["split_unit_m"] == 500.0
