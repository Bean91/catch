"""Session 34, through the database and the API: pieces store watts derived from pace (rowing only), the one-time backfill re-derives
stored pieces safely, and every body-mass figure uses the weigh-in that belongs to the performance's own day. Hand-worked values are in
tests/analytics/test_power_and_mass.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from catch.core.models import Activity, BodyComp, CanonicalActivity, Piece, PieceInterval
from catch.core.settings_store import get_settings, maintenance_marker
from catch.sync import piece as piece_sync
from catch.sync.piece_intervals import create_interval_piece
from catch.sync.piece_power import MARKER, backfill_piece_power
from conftest import TEST_PASSWORD

T0 = datetime(2026, 7, 1, 7, tzinfo=timezone.utc)
SPLITS = [{"split_index": i + 1, "distance_m": 500.0 * (i + 1), "split_s": 105.0, "rate": 30.0, "watts": None, "hr": None} for i in range(4)]


def _login(client):
    assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 200


def _workout(session, start=T0, family="rowing"):
    c = CanonicalActivity(sport_family=family, start=start, duration=3600.0)
    session.add(c)
    session.commit()
    a = Activity(source="garmin", external_id=f"g{c.id}", type="rowing_v2", start=start, duration=3600.0, sport_family=family, canonical_id=c.id)
    session.add(a)
    session.commit()
    return c


def _weigh(session, when, kg, source="withings", ext=None):
    session.add(BodyComp(source=source, external_id=ext or f"{source}-{when.isoformat()}", ts=when, weight_kg=kg))
    session.commit()


# --- watts from pace through the API ----------------------------------------------------------------


def test_a_typed_piece_gets_watts_from_its_splits_and_the_split_wins_when_forced(client, session):
    c = _workout(session)
    _login(client)
    body = {"piece_type": "2000m", "splits": SPLITS}
    piece = client.post(f"/api/activities/{c.id}/pieces", json=body).json()["piece"]
    assert piece["avg_watts"] == pytest.approx(302.343, abs=1e-3) and piece["avg_watts_basis"] == "pace"
    assert all(s["watts"] == pytest.approx(302.343, abs=1e-3) and s["watts_source"] == "pace" for s in piece["splits"])

    bad = [dict(s) for s in SPLITS]
    bad[0]["watts"] = 250.0
    refused = client.post(f"/api/activities/{c.id}/pieces", json={"piece_type": "2000m", "splits": bad}).json()
    assert refused["piece"] is None and "302 W" in json.dumps(refused["validation"])  # shown, never silently accepted
    forced = client.post(f"/api/activities/{c.id}/pieces", json={"piece_type": "2000m", "splits": bad, "force": True}).json()["piece"]
    assert forced["splits"][0]["watts"] == pytest.approx(302.343, abs=1e-3) and forced["splits"][0]["watts_entered"] == 250.0


def test_editing_a_split_re_derives_the_watts(client, session):
    c = _workout(session)
    _login(client)
    piece = client.post(f"/api/activities/{c.id}/pieces", json={"piece_type": "2000m", "splits": SPLITS}).json()["piece"]
    rows = piece["splits"]
    for r in rows:
        r["split_s"] = 100.0  # the stored watts are Catch's own: editing the split must not be flagged as a contradiction
    out = client.patch(f"/api/pieces/{piece['id']}", json={"splits": rows, "duration_s": 400.0})
    assert out.status_code == 200, out.text
    updated = out.json()["piece"]
    assert updated["avg_watts"] == pytest.approx(350.0) and updated["splits"][0]["watts"] == pytest.approx(350.0)


def test_a_bike_piece_never_gets_rowing_watts(client, session):
    c = _workout(session, family="cycling")
    _login(client)
    rows = [{"split_index": 1, "distance_m": 1000.0, "split_s": 100.0, "rate": 90.0, "watts": None, "hr": None}]
    piece = client.post(f"/api/activities/{c.id}/pieces", json={"piece_type": "custom", "splits": rows}).json()["piece"]
    assert piece["modality"] == "bike" and piece["avg_watts"] is None and piece["splits"][0]["watts"] is None
    assert piece["weight_adjusted_watts"] is None and piece["w_per_kg"] is None


def test_the_preview_endpoint_returns_the_servers_numbers_without_saving(client, session):
    _login(client)
    out = client.post("/api/pieces/preview", json={"modality": "rowing_erg", "piece_type": "2000m", "splits": SPLITS}).json()
    assert out["avg_watts"] == pytest.approx(302.343, abs=1e-3) and out["validation"]["ok"]
    assert out["splits"][0]["watts"] == pytest.approx(302.343, abs=1e-3)
    bike = client.post("/api/pieces/preview", json={"modality": "bike", "piece_type": "custom", "splits": [
        {"split_index": 1, "distance_m": 1000.0, "split_s": 100.0, "rate": 90.0, "watts": 250.0, "hr": None}]}).json()
    assert bike["avg_watts"] == 250.0 and bike["avg_watts_basis"] == "entered"
    assert session.exec(select(Piece)).all() == []


# --- body mass ---------------------------------------------------------------------------------------


def test_weight_adjusted_power_uses_that_days_weigh_in_not_todays(client, session):
    c = _workout(session)
    _weigh(session, T0 - timedelta(days=2), 80.0)
    _weigh(session, datetime.now(timezone.utc), 95.0)  # today's weight must not be used for a July piece
    _login(client)
    piece = client.post(f"/api/activities/{c.id}/pieces", json={"piece_type": "2000m", "splits": SPLITS}).json()["piece"]
    assert piece["weight_kg_used"] == 80.0 and piece["weight_date"] == (T0 - timedelta(days=2)).date().isoformat()
    assert piece["weight_adjusted_watts"] == pytest.approx(16.285, abs=1e-3)
    assert piece["w_per_kg"] == pytest.approx(302.343 / 80.0, abs=1e-3)
    assert piece["avg_watts"] == pytest.approx(302.343, abs=1e-3)  # raw watts unchanged beside it

    detail = client.get(f"/api/pieces/{piece['id']}/test-detail").json()
    assert detail["weight_adjusted_watts"] == pytest.approx(16.285, abs=1e-3) and detail["weight_kg_used"] == 80.0


def test_a_later_weigh_in_never_changes_an_older_pieces_figure(client, session):
    c = _workout(session)
    _weigh(session, T0 - timedelta(days=1), 80.0)
    _login(client)
    piece = client.post(f"/api/activities/{c.id}/pieces", json={"piece_type": "2000m", "splits": SPLITS}).json()["piece"]
    before = piece["weight_adjusted_watts"]
    _weigh(session, T0 + timedelta(days=20), 70.0)
    _weigh(session, T0 + timedelta(days=3), 72.0)
    again = client.get(f"/api/activities/{c.id}/pieces").json()["pieces"][0]
    assert again["weight_adjusted_watts"] == before and again["weight_kg_used"] == 80.0
    assert len(session.exec(select(BodyComp)).all()) == 3  # every weigh-in kept


def test_no_suitable_weigh_in_means_unavailable(client, session):
    c = _workout(session)
    _weigh(session, T0 - timedelta(days=45), 80.0)
    _weigh(session, T0 + timedelta(days=10), 79.0)
    _weigh(session, T0, 3.0, source="manual")  # implausible: never a body mass
    _login(client)
    piece = client.post(f"/api/activities/{c.id}/pieces", json={"piece_type": "2000m", "splits": SPLITS}).json()["piece"]
    assert piece["weight_adjusted_watts"] is None and piece["weight_kg_used"] is None and piece["avg_watts"] == pytest.approx(302.343, abs=1e-3)


def test_interval_scores_come_from_each_rows_own_watts_and_the_sets_from_its_aggregate(session):
    c = _workout(session)
    _weigh(session, T0 - timedelta(days=1), 80.0)
    rows = [{"target_type": "distance", "work_distance_m": 500, "work_duration_s": t, "rest_duration_s": 60} for t in (100.0, 120.0)]
    piece, _ = create_interval_piece(session, c.id, rows)
    payload = piece_sync.piece_payload(session, piece)
    kg23 = 80.0 ** (2 / 3)
    assert payload["intervals"][0]["weight_adjusted_watts"] == pytest.approx(350.0 / kg23)
    assert payload["interval_summary"]["weight_adjusted_watts"] == pytest.approx(262.960 / kg23, abs=1e-3)


def test_manual_weight_in_pounds_is_stored_in_kilograms(client, session):
    _login(client)
    out = client.post("/api/body/manual", json={"weight": 176.37, "unit": "lb", "date": "2026-06-30"})
    assert out.status_code == 200, out.text
    row = session.exec(select(BodyComp).where(BodyComp.source == "manual")).one()
    assert row.weight_kg == pytest.approx(80.0, abs=1e-3)
    assert client.post("/api/body/manual", json={"weight": 80, "unit": "stone", "date": "2026-06-30"}).status_code == 422
    assert client.post("/api/body/manual", json={"weight_kg": 0, "date": "2026-06-30"}).status_code == 422


# --- the backfill ------------------------------------------------------------------------------------


def _legacy_piece(session, canonical_id, *, modality="rowing_erg", rows=None, avg_watts=None, avg_split_s=105.0):
    p = Piece(canonical_id=canonical_id, piece_type="2000m", modality=modality, distance_m=2000.0, duration_s=420.0, avg_split_s=avg_split_s,
              avg_watts=avg_watts, splits_json=json.dumps(rows if rows is not None else SPLITS))
    session.add(p)
    session.commit()
    return p


def test_backfill_re_derives_stored_rowing_power_once_preserving_typed_values(session):
    c = _workout(session)
    typed = [dict(s, watts=w) for s, w in zip(SPLITS, (300.0, 250.0, None, 303.0))]
    rowing = _legacy_piece(session, c.id, rows=typed, avg_watts=284.3)  # the old plain mean of split watts
    bike_rows = [{"split_index": 1, "distance_m": 1000.0, "split_s": 100.0, "rate": 90, "watts": 240.0, "hr": None}]
    bike = _legacy_piece(session, c.id, modality="bike", rows=bike_rows, avg_watts=240.0, avg_split_s=100.0)

    changed = backfill_piece_power(session)
    assert changed == {c.id} and maintenance_marker(session, MARKER) == 1
    session.refresh(rowing)
    session.refresh(bike)
    rows = json.loads(rowing.splits_json)
    assert rowing.avg_watts == pytest.approx(302.343, abs=1e-3)
    assert [round(r["watts"], 3) for r in rows] == [302.343] * 4
    assert rows[1]["watts_entered"] == 250.0 and "watts_entered" not in rows[0] and "watts_entered" not in rows[3]
    assert bike.avg_watts == 240.0 and json.loads(bike.splits_json)[0]["watts"] == 240.0  # never the rowing formula

    snapshot = (rowing.splits_json, rowing.avg_watts)
    assert backfill_piece_power(session) == set()  # marked: a second run is a no-op
    session.refresh(rowing)
    assert (rowing.splits_json, rowing.avg_watts) == snapshot
    assert "_maintenance" not in get_settings(session)


def test_backfill_leaves_a_contradictory_typed_interval_watts_alone(session):
    c = _workout(session)
    p = Piece(canonical_id=c.id, piece_type="custom", modality="rowing_erg", has_intervals=True, splits_json="[]")
    session.add(p)
    session.commit()
    session.add(PieceInterval(piece_id=p.id, position=0, target_type="distance", work_distance_m=500, work_duration_s=105.0, avg_watts=250.0))
    session.add(PieceInterval(piece_id=p.id, position=1, target_type="distance", work_distance_m=500, work_duration_s=105.0, avg_watts=None))
    session.commit()
    backfill_piece_power(session)
    rows = session.exec(select(PieceInterval).where(PieceInterval.piece_id == p.id).order_by(PieceInterval.position)).all()
    assert rows[0].avg_watts == 250.0 and rows[1].avg_watts == pytest.approx(302.343, abs=1e-3)
    session.refresh(p)
    assert p.avg_watts == pytest.approx(302.343, abs=1e-3)


def test_maintenance_runs_the_backfill_and_survives_its_failure(session, monkeypatch):
    import contextlib

    from catch.sync import scheduler

    @contextlib.contextmanager
    def ctx():
        yield session

    monkeypatch.setattr(scheduler, "get_session", ctx)
    c = _workout(session)
    piece = _legacy_piece(session, c.id, avg_watts=1.0)
    scheduler.run_maintenance()
    session.refresh(piece)
    assert piece.avg_watts == pytest.approx(302.343, abs=1e-3) and maintenance_marker(session, MARKER) == 1
    monkeypatch.setattr("catch.sync.piece_power.backfill_piece_power", lambda s: (_ for _ in ()).throw(RuntimeError("bug")))
    assert scheduler._backfill_piece_power(session) == set()  # a bug in the upgrade never breaks maintenance


# --- the AI coach never sees body mass unless wellness is shared ------------------------------------


@pytest.mark.real_ai_sharing
def test_body_mass_figures_are_stripped_from_workout_tools_when_wellness_is_off(session):
    from catch.coach import ai_sharing

    ai_sharing.update(session, acknowledge=True, categories={"workouts": True})
    result = {"piece": {"avg_watts": 302.3, "w_per_kg": 3.78, "weight_adjusted_watts": 16.3, "weight_kg_used": 80.0, "weight_date": "2026-06-29"},
              "sets": [{"load_kg": 60, "bodyweight_kg_used": 80.0}]}
    limited = ai_sharing.limit_result(session, "get_test", result)
    assert limited["piece"] == {"avg_watts": 302.3} and limited["sets"] == [{"load_kg": 60}]
    ai_sharing.update(session, acknowledge=True, categories={"workouts": True, "wellness": True})
    assert ai_sharing.limit_result(session, "get_test", result) == result
