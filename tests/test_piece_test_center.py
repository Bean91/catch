from __future__ import annotations

from datetime import datetime, timezone

from catch.core.models import Activity, CanonicalActivity
from catch.sync.samples import store_samples
from conftest import TEST_PASSWORD

T0 = datetime(2026, 7, 1, 7, tzinfo=timezone.utc)

_SPLITS = [
    {"split_index": 1, "distance_m": 500.0, "split_s": 96.8, "rate": 32.0, "watts": None, "hr": None},
    {"split_index": 2, "distance_m": 1000.0, "split_s": 98.9, "rate": 30.0, "watts": None, "hr": None},
    {"split_index": 3, "distance_m": 1500.0, "split_s": 99.0, "rate": 31.0, "watts": None, "hr": None},
    {"split_index": 4, "distance_m": 2000.0, "split_s": 97.7, "rate": 32.0, "watts": None, "hr": None},
]


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed_activity_with_piece(session, client):
    a = Activity(source="garmin", external_id="g1", type="rowing_v2", start=T0, duration=3600.0, sport_family="rowing")
    session.add(a)
    session.commit()
    c = CanonicalActivity(sport_family="rowing")
    session.add(c)
    session.commit()
    a.canonical_id = c.id
    session.add(a)
    session.commit()
    hr = [130.0] * 3600
    store_samples(session, a.id, start=T0, hr=hr, power=[None] * 3600, cadence=[20.0] * 3600)

    resp = client.post(
        f"/api/activities/{a.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": _SPLITS, "distance_m": 2000.0, "duration_s": 392.4},
    )
    return a, resp.json()["piece"]


def test_piece_shows_up_in_get_tests_as_a_first_class_row(client, session):
    _login(client)
    _seed_activity_with_piece(session, client)

    resp = client.get("/api/tests", params={"type": "2000m"})
    assert resp.status_code == 200
    rows = resp.json()["tests"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "piece"
    assert rows[0]["duration_s"] == 392.4


def test_piece_test_detail_returns_pacing_analysis_from_its_own_splits(client, session):
    _login(client)
    activity, piece = _seed_activity_with_piece(session, client)

    resp = client.get(f"/api/pieces/{piece['id']}/test-detail")
    assert resp.status_code == 200
    body = resp.json()
    assert body["test_type"] == "2000m"
    assert body["pacing_analysis"]["even_split_s"] is not None
    assert len(body["pacing_analysis"]["splits"]) == 4
    # Links back to the containing (whole-session) activity for the full HR-chart experience,
    # never a duplicated chart of its own (DESIGN.md's pacing-chart precedent).
    assert body["activity"]["id"] == activity.canonical_id


def test_piece_counts_toward_personal_bests(client, session):
    _login(client)
    _seed_activity_with_piece(session, client)

    resp = client.get("/api/pbs")
    assert resp.status_code == 200
    pb = resp.json()["2000m"]
    assert pb is not None
    assert pb["duration_s"] == 392.4
    assert pb["piece_id"] is not None


def test_piece_unknown_id_404s(client, session):
    _login(client)
    assert client.get("/api/pieces/999/test-detail").status_code == 404
