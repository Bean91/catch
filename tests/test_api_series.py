from __future__ import annotations

from datetime import date, timedelta

from catch.core.models import DailyWellness
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed_wellness(session, n_days: int, start: date):
    for i in range(n_days):
        session.add(DailyWellness(date=start + timedelta(days=i), resting_hr=50 + (i % 5), hrv_rmssd=60.0 + i))
    session.commit()


def test_series_unknown_metric_rejected(client):
    _login(client)
    resp = client.get("/api/series", params={"metrics": "not_a_real_metric"})
    assert resp.status_code == 400


def test_series_passthrough_when_under_point_budget(client, session):
    start = date(2026, 1, 1)
    _seed_wellness(session, 10, start)
    _login(client)
    resp = client.get("/api/series", params={"metrics": "resting_hr", "points": 400})
    assert resp.status_code == 200
    body = resp.json()["series"]["resting_hr"]
    assert body["raw_count"] == 10
    assert body["returned_count"] == 10
    assert body["points"][0]["date"] == start.isoformat()
    assert body["points"][-1]["date"] == (start + timedelta(days=9)).isoformat()


def test_series_downsamples_long_history_to_requested_points(client, session):
    start = date(2024, 1, 1)
    _seed_wellness(session, 400, start)
    _login(client)
    resp = client.get("/api/series", params={"metrics": "resting_hr", "points": 50})
    body = resp.json()["series"]["resting_hr"]
    assert body["raw_count"] == 400
    assert body["returned_count"] == 50
    assert body["points"][0]["date"] == start.isoformat()
    assert body["points"][-1]["date"] == (start + timedelta(days=399)).isoformat()
    for p in body["points"]:
        assert p["value_min"] <= p["value"] <= p["value_max"]


def test_series_respects_from_to_window(client, session):
    start = date(2026, 1, 1)
    _seed_wellness(session, 30, start)
    _login(client)
    resp = client.get(
        "/api/series",
        params={"metrics": "resting_hr", "from": "2026-01-10", "to": "2026-01-15", "points": 400},
    )
    body = resp.json()["series"]["resting_hr"]
    assert body["raw_count"] == 6
    assert body["points"][0]["date"] == "2026-01-10"
    assert body["points"][-1]["date"] == "2026-01-15"


def test_series_multiple_metrics_in_one_call(client, session):
    _seed_wellness(session, 5, date(2026, 1, 1))
    _login(client)
    resp = client.get("/api/series", params={"metrics": "resting_hr,hrv_rmssd", "points": 400})
    series = resp.json()["series"]
    assert set(series) == {"resting_hr", "hrv_rmssd"}


def test_series_empty_metric_returns_empty_points(client):
    _login(client)
    resp = client.get("/api/series", params={"metrics": "resting_hr", "points": 400})
    body = resp.json()["series"]["resting_hr"]
    assert body == {"points": [], "raw_count": 0, "returned_count": 0}


def test_series_cache_invalidated_by_recompute_scores(client, session):
    _seed_wellness(session, 5, date(2026, 1, 1))
    _login(client)
    first = client.get("/api/series", params={"metrics": "resting_hr", "points": 400}).json()
    assert first["series"]["resting_hr"]["raw_count"] == 5

    _seed_wellness(session, 5, date(2026, 2, 1))
    from catch.sync.scoring import recompute_scores

    recompute_scores(session)

    second = client.get("/api/series", params={"metrics": "resting_hr", "points": 400}).json()
    assert second["series"]["resting_hr"]["raw_count"] == 10


def test_series_w_per_kg_carries_activity_id_for_tap_to_open(client, session):
    from datetime import datetime, timezone

    from catch.core.models import Activity, BodyComp

    session.add(BodyComp(source="withings", external_id="b1", ts=datetime(2026, 1, 1, tzinfo=timezone.utc), weight_kg=80.0))
    session.add(
        Activity(source="concept2", external_id="c1", type="rower", start=datetime(2026, 1, 1, 12, tzinfo=timezone.utc), avg_power=320.0)
    )
    session.commit()
    from catch.sync.matching import run_matching

    run_matching(session)

    _login(client)
    resp = client.get("/api/series", params={"metrics": "w_per_kg", "points": 400})
    points = resp.json()["series"]["w_per_kg"]["points"]
    assert len(points) == 1
    assert points[0]["activity_id"] is not None


def test_series_load_acr_carries_component_fields(client, session):
    import json

    from catch.core.models import DailyScore

    for i in range(3):
        session.add(
            DailyScore(
                date=date(2026, 1, 1) + timedelta(days=i),
                load_json=json.dumps(
                    {"value": 1.0 + i * 0.1, "band": "optimal", "components": [{"acute_7d": 50.0 + i, "chronic_42d": 45.0, "form": -5.0}]}
                ),
            )
        )
    session.commit()
    _login(client)
    resp = client.get("/api/series", params={"metrics": "load_acr", "points": 400})
    points = resp.json()["series"]["load_acr"]["points"]
    assert all("acute_7d" in p and "form" in p for p in points)
