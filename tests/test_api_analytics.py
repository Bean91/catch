from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from catch.core.models import Activity, BodyComp, DailyScore, DailyWellness, Stroke
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_today_with_no_data_yet(client):
    _login(client)
    resp = client.get("/api/today")
    assert resp.status_code == 200
    body = resp.json()
    assert body["recovery"] is None
    assert "recommendation" in body


def test_today_reflects_cached_daily_score(client, session):
    today = date.today()
    session.add(DailyWellness(date=today, sleep_seconds=25000, sleep_score=85))
    session.add(
        DailyScore(
            date=today,
            recovery_json='{"value": 80.0, "band": "green", "components": [], "explanation": "x"}',
            strain_json='{"value": 5.0, "band": "light", "components": [], "explanation": "x"}',
            load_json='{"value": 1.0, "band": "optimal", "components": [], "explanation": "x"}',
        )
    )
    session.commit()

    _login(client)
    resp = client.get("/api/today")
    body = resp.json()
    assert body["recovery"]["band"] == "green"
    assert body["sleep_last_night"]["seconds"] == 25000
    assert "clear for a harder session" in body["recommendation"]


def test_trends_rejects_unknown_metric(client):
    _login(client)
    resp = client.get("/api/trends", params={"metric": "not_a_real_metric"})
    assert resp.status_code == 400


def test_trends_wellness_metric(client, session):
    day = date(2026, 1, 1)
    session.add(DailyWellness(date=day, resting_hr=48))
    session.commit()

    _login(client)
    resp = client.get("/api/trends", params={"metric": "resting_hr", "from": "2026-01-01", "to": "2026-01-02"})
    assert resp.status_code == 200
    assert resp.json() == [{"date": "2026-01-01", "value": 48}]


def test_erg_results_filters_to_concept2(client, session):
    session.add(Activity(source="garmin", external_id="g1", type="rowing_v2", start=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    session.add(Activity(source="concept2", external_id="c1", type="rower", start=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    session.commit()

    _login(client)
    resp = client.get("/api/erg/results")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["source"] == "concept2"


def test_erg_strokes_returns_404_for_non_concept2_activity(client, session):
    session.add(Activity(source="garmin", external_id="g1", type="rowing_v2"))
    session.commit()

    _login(client)
    resp = client.get("/api/erg/1/strokes")
    assert resp.status_code == 404


def test_erg_strokes_groups_by_interval(client, session):
    activity = Activity(source="concept2", external_id="c1", type="rower")
    session.add(activity)
    session.commit()
    session.add(Stroke(activity_id=activity.id, seq=0, interval_index=0, t=10.0, distance=50.0, watts=300, stroke_rate=30, pace_500m=105.0))
    session.add(Stroke(activity_id=activity.id, seq=1, interval_index=1, t=5.0, distance=20.0, watts=280, stroke_rate=28, pace_500m=110.0))
    session.commit()

    _login(client)
    resp = client.get(f"/api/erg/{activity.id}/strokes")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["strokes"]) == 2
    assert set(body["technique_by_interval"].keys()) == {"0", "1"}
    # Neither stroke has an hr reading -> no per-sample HR to bucket into zones.
    assert body["time_in_zone_by_interval"]["0"] is None
    assert body["time_in_zone_by_interval"]["1"] is None


def test_erg_strokes_time_in_zone_with_hr(client, session):
    from catch.core.settings_store import update_settings

    update_settings(session, {"max_hr": 190})
    activity = Activity(source="concept2", external_id="c2", type="rower")
    session.add(activity)
    session.commit()
    session.add(Stroke(activity_id=activity.id, seq=0, interval_index=0, t=0.0, hr=150))
    session.add(Stroke(activity_id=activity.id, seq=1, interval_index=0, t=60.0, hr=150))
    session.commit()

    _login(client)
    resp = client.get(f"/api/erg/{activity.id}/strokes")
    totals = resp.json()["time_in_zone_by_interval"]["0"]
    # 150/190 = 78.9% -> UT1; first sample duration=t itself (0), second=60-0=60.
    assert totals["UT1"] == 60.0


def test_erg_results_includes_nearest_weight(client, session):
    when = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    session.add(BodyComp(source="withings", external_id="b1", ts=when - timedelta(days=1), weight_kg=80.0))
    session.add(
        Activity(source="concept2", external_id="c1", type="rower", start=when, avg_power=320.0, duration=1200.0)
    )
    session.commit()

    _login(client)
    resp = client.get("/api/erg/results")
    row = resp.json()[0]
    assert row["weight_kg"] == 80.0
    assert row["w_per_kg"] == 4.0


def test_predict_2k_excludes_interval_workouts_and_old_pieces(client, session):
    session.add(
        Activity(
            source="concept2",
            external_id="interval1",
            type="rower",
            workout_type="FixedDistanceInterval",
            start=datetime.now(timezone.utc) - timedelta(days=5),
            distance=2000,
            duration=600.0,
        )
    )
    session.add(
        Activity(
            source="concept2",
            external_id="old1",
            type="rower",
            workout_type="JustRow",
            start=datetime.now(timezone.utc) - timedelta(days=400),
            distance=5000,
            duration=1100.0,
        )
    )
    session.commit()

    _login(client)
    resp = client.get("/api/predict/2k")
    assert resp.json()["band"] == "insufficient_data"


def test_predict_2k_with_no_history(client):
    _login(client)
    resp = client.get("/api/predict/2k")
    assert resp.status_code == 200
    assert resp.json()["band"] == "insufficient_data"


def test_predict_2k_uses_best_piece_per_bucket(client, session):
    session.add(
        Activity(
            source="concept2",
            external_id="c1",
            type="rower",
            start=datetime.now(timezone.utc) - timedelta(days=10),
            distance=6000,
            duration=660.0,  # 110.0 s/500m
        )
    )
    session.commit()

    _login(client)
    resp = client.get("/api/predict/2k")
    body = resp.json()
    assert body["value"] is not None
    assert body["components"][0]["distance_m"] == 6000


def test_get_settings_returns_defaults(client):
    _login(client)
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["recovery_green"] == 67


def test_put_settings_updates_and_rejects_unknown_keys(client):
    _login(client)
    resp = client.put("/api/settings", json={"max_hr": 188})
    assert resp.status_code == 200
    assert resp.json()["max_hr"] == 188

    resp2 = client.get("/api/settings")
    assert resp2.json()["max_hr"] == 188

    bad = client.put("/api/settings", json={"not_a_real_setting": 1})
    assert bad.status_code == 422


def test_settings_require_auth(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 401
