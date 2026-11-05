from __future__ import annotations

import uuid

from catch.core.models import Exercise
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed_exercise(session, name="Barbell Squat") -> Exercise:
    row = Exercise(
        name=name,
        default_equipment_type="barbell",
        movement_pattern="squat",
        primary_muscles_json='["quadriceps"]',
        secondary_muscles_json='["glutes"]',
        custom=True,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_requires_auth(client):
    r = client.get("/api/gym/exercises")
    assert r.status_code == 401


def test_list_and_search_exercises(client, session):
    _login(client)
    _seed_exercise(session, name="Barbell Bench Press")
    _seed_exercise(session, name="Dumbbell Row")

    r = client.get("/api/gym/exercises")
    assert r.status_code == 200
    assert len(r.json()["exercises"]) == 2

    r = client.get("/api/gym/exercises", params={"q": "bench"})
    assert len(r.json()["exercises"]) == 1


def test_create_custom_exercise(client, session):
    _login(client)
    r = client.post(
        "/api/gym/exercises",
        json={
            "name": "Reverse Nordic",
            "default_equipment_type": "bodyweight",
            "movement_pattern": "other",
            "primary_muscles": ["quadriceps"],
        },
    )
    assert r.status_code == 200
    assert r.json()["custom"] is True


def test_gym_and_station_round_trip(client, session):
    _login(client)
    r = client.post("/api/gym/gyms", json={"name": "Uni Gym"})
    gym_id = r.json()["id"]

    r = client.post(
        "/api/gym/gyms/{}/stations".format(gym_id),
        json={"name": "Cable 2", "equipment_type": "cable", "config": {"pulley_multiplier": 0.5}},
    )
    assert r.status_code == 200
    station_id = r.json()["id"]

    r = client.get(f"/api/gym/gyms/{gym_id}/stations")
    assert len(r.json()["stations"]) == 1

    r = client.put(
        f"/api/gym/gyms/{gym_id}/stations/{station_id}",
        json={"name": "Cable 2 (renamed)", "equipment_type": "cable", "config": {"pulley_multiplier": 0.25}},
    )
    assert r.json()["config"]["pulley_multiplier"] == 0.25


def test_sync_sets_idempotent_and_recomputes_scores(client, session):
    _login(client)
    exercise = _seed_exercise(session)
    session_id = str(uuid.uuid4())
    set_id = str(uuid.uuid4())

    payload = {
        "client_session_id": session_id,
        "sets": [
            {
                "client_id": set_id,
                "exercise_id": exercise.id,
                "equipment_type": "barbell",
                "load_kg": 100.0,
                "bar_weight_kg": 20.0,
                "reps": 5,
            }
        ],
        "deleted_client_ids": [],
    }
    r = client.post("/api/gym/sessions/sync", json=payload)
    assert r.status_code == 200
    assert r.json()["sets"][0]["effective_load_kg"] == 120.0

    # Retry the exact same payload — must not duplicate.
    r2 = client.post("/api/gym/sessions/sync", json=payload)
    assert r2.status_code == 200

    r3 = client.get(f"/api/gym/sessions/{session_id}/sets")
    assert len(r3.json()["sets"]) == 1


def test_delete_via_sync_tombstones_the_set(client, session):
    _login(client)
    exercise = _seed_exercise(session)
    session_id = str(uuid.uuid4())
    set_id = str(uuid.uuid4())

    client.post(
        "/api/gym/sessions/sync",
        json={
            "client_session_id": session_id,
            "sets": [{"client_id": set_id, "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 60.0, "reps": 8}],
            "deleted_client_ids": [],
        },
    )
    r = client.post("/api/gym/sessions/sync", json={"client_session_id": session_id, "sets": [], "deleted_client_ids": [set_id]})
    assert r.status_code == 200

    r2 = client.get(f"/api/gym/sessions/{session_id}/sets")
    assert r2.json()["sets"] == []


def test_repeat_last_workout_and_last_sets_for_exercise(client, session):
    _login(client)
    exercise = _seed_exercise(session)
    session_id = str(uuid.uuid4())
    client.post(
        "/api/gym/sessions/sync",
        json={
            "client_session_id": session_id,
            "sets": [{"client_id": str(uuid.uuid4()), "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 80.0, "reps": 5, "seq": 0}],
            "deleted_client_ids": [],
        },
    )
    r = client.get("/api/gym/repeat-last-workout")
    assert r.json()["plan"][0]["exercise_id"] == exercise.id

    r2 = client.get(f"/api/gym/exercises/{exercise.id}/last")
    assert r2.json()["sets"][0]["load_kg"] == 80.0


def test_templates_crud(client, session):
    _login(client)
    r = client.post("/api/gym/templates", json={"name": "Push Day", "items": [{"exercise_id": 1}]})
    assert r.status_code == 200
    template_id = r.json()["id"]

    r = client.get("/api/gym/templates")
    assert len(r.json()["templates"]) == 1

    r = client.put(f"/api/gym/templates/{template_id}", json={"name": "Push Day v2", "items": []})
    assert r.json()["name"] == "Push Day v2"

    r = client.delete(f"/api/gym/templates/{template_id}")
    assert r.json()["deleted"] is True
    assert client.get("/api/gym/templates").json()["templates"] == []


def test_muscle_readiness_endpoint(client, session):
    _login(client)
    exercise = _seed_exercise(session)
    session_id = str(uuid.uuid4())
    client.post(
        "/api/gym/sessions/sync",
        json={
            "client_session_id": session_id,
            "sets": [{"client_id": str(uuid.uuid4()), "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 100.0, "bar_weight_kg": 20.0, "reps": 5}],
            "deleted_client_ids": [],
        },
    )
    r = client.get("/api/gym/muscle-readiness")
    assert r.status_code == 200
    assert r.json()["by_muscle"]["quadriceps"] > 0


def test_activity_detail_includes_strength_sets_and_muscular_breakdown(client, session):
    _login(client)
    exercise = _seed_exercise(session)
    session_id = str(uuid.uuid4())
    client.post(
        "/api/gym/sessions/sync",
        json={
            "client_session_id": session_id,
            "sets": [{"client_id": str(uuid.uuid4()), "exercise_id": exercise.id, "equipment_type": "barbell", "load_kg": 100.0, "bar_weight_kg": 20.0, "reps": 5}],
            "deleted_client_ids": [],
        },
    )
    activities = client.get("/api/activities").json()["items"]
    strength_activity = next(a for a in activities if a["sport_family"] == "strength")
    detail = client.get(f"/api/activities/{strength_activity['id']}").json()
    assert len(detail["strength_sets"]) == 1
    assert detail["muscular_by_muscle"]["quadriceps"] > 0
