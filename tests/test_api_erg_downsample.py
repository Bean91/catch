from __future__ import annotations

from catch.core.models import Activity, Stroke
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed_long_piece(session, n_strokes: int) -> Activity:
    activity = Activity(source="concept2", external_id="c1", type="rower")
    session.add(activity)
    session.commit()
    for i in range(n_strokes):
        session.add(
            Stroke(
                activity_id=activity.id,
                seq=i,
                interval_index=0,
                t=float(i * 2),
                distance=float(i * 10),
                watts=250.0 + (i % 7),
                stroke_rate=28 + (i % 3),
                pace_500m=120.0 - (i % 5),
                hr=150 + (i % 10),
            )
        )
    session.commit()
    return activity


def test_erg_strokes_unbounded_by_default(client, session):
    activity = _seed_long_piece(session, 2000)
    _login(client)
    resp = client.get(f"/api/erg/{activity.id}/strokes")
    body = resp.json()
    assert body["stroke_count"] == 2000
    assert body["returned_stroke_count"] == 2000
    assert len(body["strokes"]) == 2000


def test_erg_strokes_downsampled_to_points(client, session):
    activity = _seed_long_piece(session, 2000)
    _login(client)
    resp = client.get(f"/api/erg/{activity.id}/strokes", params={"points": 100})
    body = resp.json()
    assert body["stroke_count"] == 2000
    assert body["returned_stroke_count"] == 100
    assert len(body["strokes"]) == 100
    strokes = body["strokes"]
    assert strokes[0]["distance_cum"] == 0.0
    assert strokes[-1]["distance_cum"] == (1999 * 10.0)
    # x-aligned: watts/rate/hr survive on the same chosen strokes, not recomputed/averaged.
    assert all(s["watts"] is not None for s in strokes)


def test_erg_strokes_distance_window_for_zoom(client, session):
    activity = _seed_long_piece(session, 500)
    _login(client)
    resp = client.get(f"/api/erg/{activity.id}/strokes", params={"distance_min": 1000, "distance_max": 2000})
    strokes = resp.json()["strokes"]
    assert all(1000 <= s["distance_cum"] <= 2000 for s in strokes)
    assert len(strokes) > 0


def test_erg_strokes_distance_window_still_downsamples(client, session):
    activity = _seed_long_piece(session, 2000)
    _login(client)
    resp = client.get(
        f"/api/erg/{activity.id}/strokes",
        params={"distance_min": 0, "distance_max": 5000, "points": 50},
    )
    body = resp.json()
    assert body["returned_stroke_count"] == 50
    assert all(s["distance_cum"] <= 5000 for s in body["strokes"])


def test_erg_strokes_technique_computed_over_full_resolution_not_downsampled(client, session):
    activity = _seed_long_piece(session, 2000)
    _login(client)
    full = client.get(f"/api/erg/{activity.id}/strokes").json()
    downsampled = client.get(f"/api/erg/{activity.id}/strokes", params={"points": 50}).json()
    assert full["interval_summary"] == downsampled["interval_summary"]
    assert full["technique_by_interval"] == downsampled["technique_by_interval"]
