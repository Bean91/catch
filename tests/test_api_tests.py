from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from catch.core.models import Activity, Event, Stroke
from catch.sync.matching import run_matching
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed_2000m_piece(session, external_id: str = "c1", start: datetime | None = None) -> Activity:
    activity = Activity(
        source="concept2",
        external_id=external_id,
        type="rower",
        start=start or datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        duration=400.0,
        distance=2000.0,
        avg_power=250.0,
        stroke_rate=32.0,
    )
    session.add(activity)
    session.commit()
    run_matching(session)
    session.refresh(activity)
    for i in range(1, 5):  # even 100s/500m splits, no interval boundaries
        session.add(Stroke(activity_id=activity.id, seq=i, interval_index=0, t=100.0 * i, distance=500.0 * i))
    session.commit()
    return activity


def test_untagged_standard_piece_shows_up_as_a_candidate(client, session):
    _seed_2000m_piece(session)
    _login(client)
    resp = client.get("/api/tests/candidates")
    assert resp.status_code == 200
    candidates = resp.json()["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["suggested_test_type"] == "2000m"


def test_a_non_standard_piece_is_not_a_candidate(client, session):
    activity = Activity(source="concept2", external_id="c2", type="rower", start=datetime(2026, 2, 1, tzinfo=timezone.utc), duration=900.0, distance=3333.0)
    session.add(activity)
    session.commit()
    run_matching(session)

    _login(client)
    resp = client.get("/api/tests/candidates")
    assert resp.json()["candidates"] == []


def test_confirming_a_candidate_tags_it_as_a_test(client, session):
    activity = _seed_2000m_piece(session)
    _login(client)
    resp = client.patch(f"/api/activities/{activity.canonical_id}", json={"tags": ["test"], "test_type": "2000m"})
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["test"]
    assert resp.json()["test_type"] == "2000m"

    candidates = client.get("/api/tests/candidates").json()["candidates"]
    assert candidates == []  # no longer a candidate once confirmed
    tests = client.get("/api/tests", params={"type": "2000m"}).json()["tests"]
    assert len(tests) == 1
    assert tests[0]["canonical_id"] == activity.canonical_id


def test_patch_rejects_unknown_test_type(client, session):
    activity = _seed_2000m_piece(session)
    _login(client)
    resp = client.patch(f"/api/activities/{activity.canonical_id}", json={"test_type": "marathon"})
    assert resp.status_code == 422


def test_test_detail_has_pacing_analysis_and_w_per_kg(client, session):
    activity = _seed_2000m_piece(session)
    _login(client)
    client.patch(f"/api/activities/{activity.canonical_id}", json={"tags": ["test"], "test_type": "2000m"})

    resp = client.get(f"/api/tests/{activity.canonical_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["test_type"] == "2000m"
    analysis = body["pacing_analysis"]
    assert len(analysis["splits"]) == 4
    assert analysis["even_split_s"] == 100.0
    assert analysis["segments"]["sprint"] is not None


def test_test_detail_404s_for_an_untagged_workout(client, session):
    activity = _seed_2000m_piece(session)
    _login(client)
    resp = client.get(f"/api/tests/{activity.canonical_id}")
    assert resp.status_code == 404


def test_compare_to_earlier_finds_the_prior_same_type_test(client, session):
    earlier = _seed_2000m_piece(session, external_id="c1", start=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc))
    later = _seed_2000m_piece(session, external_id="c2", start=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc))
    _login(client)
    client.patch(f"/api/activities/{earlier.canonical_id}", json={"tags": ["test"], "test_type": "2000m"})
    client.patch(f"/api/activities/{later.canonical_id}", json={"tags": ["test"], "test_type": "2000m"})

    resp = client.get(f"/api/tests/{later.canonical_id}")
    assert resp.json()["compare_to_earlier"]["canonical_id"] == earlier.canonical_id


def test_make_pacing_plan_splits_sum_to_goal(client, session):
    _login(client)
    resp = client.post("/api/tests/pacing-plan", json={"test_type": "2000m", "goal_time_s": 420.0, "style": "even"})
    assert resp.status_code == 200
    plan = resp.json()["plan"]
    assert sum(s["target_split_s"] for s in plan["splits"]) == 420.0
    assert resp.json()["saved_to_event"] is None  # save_to_next_event defaults to false


def test_make_pacing_plan_requires_distance_for_custom(client, session):
    _login(client)
    resp = client.post("/api/tests/pacing-plan", json={"test_type": "custom", "goal_time_s": 420.0, "style": "even"})
    assert resp.status_code == 422


def test_make_pacing_plan_saves_to_the_next_event_and_shows_on_test_detail(client, session):
    event = Event(name="Winter 2k", date=date.today() + timedelta(days=30), type="2k_test")
    session.add(event)
    session.commit()

    activity = _seed_2000m_piece(session)
    _login(client)
    client.patch(f"/api/activities/{activity.canonical_id}", json={"tags": ["test"], "test_type": "2000m"})

    resp = client.post(
        "/api/tests/pacing-plan",
        json={"test_type": "2000m", "goal_time_s": 400.0, "style": "even", "save_to_next_event": True},
    )
    assert resp.json()["saved_to_event"]["id"] == event.id

    detail = client.get(f"/api/tests/{activity.canonical_id}").json()
    assert detail["plan"] is not None
    assert detail["pacing_analysis"]["vs_plan"] is not None


def test_projection_reports_insufficient_data_with_fewer_than_three_tests(client, session):
    activity = _seed_2000m_piece(session)
    _login(client)
    client.patch(f"/api/activities/{activity.canonical_id}", json={"tags": ["test"], "test_type": "2000m"})

    resp = client.get("/api/tests/projection", params={"type": "2000m"})
    assert resp.status_code == 200
    assert resp.json()["value"] is None
