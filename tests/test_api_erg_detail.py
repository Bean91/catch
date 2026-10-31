from __future__ import annotations

from catch.core.models import Activity, Stroke
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_erg_strokes_interval_summary_and_drift(client, session):
    activity = Activity(source="concept2", external_id="c1", type="rower")
    session.add(activity)
    session.commit()
    # Rep 1: 500m in 100s -> split 100s/500m. Rep 2: 500m in 110s -> split 110s/500m (10% slower).
    session.add(Stroke(activity_id=activity.id, seq=0, interval_index=0, t=50.0, distance=250.0, watts=300, stroke_rate=30, hr=150))
    session.add(Stroke(activity_id=activity.id, seq=1, interval_index=0, t=100.0, distance=500.0, watts=300, stroke_rate=30, hr=155))
    session.add(Stroke(activity_id=activity.id, seq=2, interval_index=1, t=55.0, distance=250.0, watts=280, stroke_rate=28, hr=158))
    session.add(Stroke(activity_id=activity.id, seq=3, interval_index=1, t=110.0, distance=500.0, watts=280, stroke_rate=28, hr=160))
    session.commit()

    _login(client)
    resp = client.get(f"/api/erg/{activity.id}/strokes")
    assert resp.status_code == 200
    body = resp.json()

    rep0 = body["interval_summary"]["0"]
    rep1 = body["interval_summary"]["1"]
    assert rep0["avg_split_500m"] == 100.0
    assert rep1["avg_split_500m"] == 110.0
    assert rep0["drift_vs_rep1_pct"] == 0.0
    assert rep1["drift_vs_rep1_pct"] == 10.0
    assert rep0["avg_watts"] == 300.0
    assert rep0["avg_hr"] == 152.5

    # Cumulative distance/time should not reset to 0 at the rep-1/rep-2 boundary.
    strokes = body["strokes"]
    assert strokes[0]["distance_cum"] == 250.0
    assert strokes[1]["distance_cum"] == 500.0
    assert strokes[2]["distance_cum"] == 750.0  # 500 (rep0 total) + 250
    assert strokes[3]["distance_cum"] == 1000.0
    assert strokes[2]["t_cum"] == 155.0  # 100 (rep0 total) + 55
