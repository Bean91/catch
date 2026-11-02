from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from catch.core.models import Activity, DailyScore, Note
from catch.sync.matching import run_matching
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed(session, *activities):
    for a in activities:
        session.add(a)
    session.commit()
    run_matching(session)
    for a in activities:
        session.refresh(a)
    return activities


def test_activities_category_filter_erg(client, session):
    g1, g2, c1 = _seed(
        session,
        Activity(source="garmin", external_id="g1", type="indoor_rowing", start=datetime(2026, 1, 1, tzinfo=timezone.utc), duration=600.0),
        Activity(source="garmin", external_id="g2", type="rowing_v2", start=datetime(2026, 1, 2, tzinfo=timezone.utc), duration=600.0),
        Activity(source="concept2", external_id="c1", type="rower", start=datetime(2026, 1, 3, tzinfo=timezone.utc), duration=600.0),
    )

    _login(client)
    resp = client.get("/api/activities", params={"category": "erg"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {i["id"] for i in items} == {g1.canonical_id, c1.canonical_id}
    assert all(i["category"] == "erg" for i in items)


def test_activities_category_filter_on_water(client, session):
    g2, c2, g3 = _seed(
        session,
        Activity(source="garmin", external_id="g2", type="rowing_v2", start=datetime(2026, 1, 2, tzinfo=timezone.utc), duration=600.0),
        Activity(source="concept2", external_id="c2", type="water", start=datetime(2026, 1, 3, tzinfo=timezone.utc), duration=600.0),
        Activity(source="garmin", external_id="g3", type="indoor_rowing", start=datetime(2026, 1, 4, tzinfo=timezone.utc), duration=600.0),
    )

    _login(client)
    resp = client.get("/api/activities", params={"category": "on_water"})
    items = resp.json()["items"]
    assert {i["id"] for i in items} == {g2.canonical_id, c2.canonical_id}


def test_activities_category_rejects_unknown(client):
    _login(client)
    resp = client.get("/api/activities", params={"category": "bogus"})
    assert resp.status_code == 400


def test_activities_merges_matched_pair_into_one_canonical(client, session):
    """Session 8/12 (see PLAN.md): a Garmin watch + Concept2 PM5 recording of the same row
    auto-merge into one canonical — the Workouts list shows it once, superseding the old
    session-2 `linked_activity_id` dedup this replaced."""
    c2, garmin = _seed(
        session,
        Activity(source="concept2", external_id="c1", type="rower", start=datetime(2026, 1, 1, 7, 0, 0, tzinfo=timezone.utc), duration=600.0),
        Activity(source="garmin", external_id="g1", type="indoor_rowing", start=datetime(2026, 1, 1, 7, 0, 10, tzinfo=timezone.utc), duration=600.0),
    )

    _login(client)
    resp = client.get("/api/activities")
    items = resp.json()["items"]
    assert len(items) == 1
    assert {s["source"] for s in items[0]["sources"]} == {"concept2", "garmin"}


def test_activities_pagination_cursor(client, session):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = _seed(
        session,
        *[
            Activity(source="garmin", external_id=f"g{i}", type="strength_training", start=base + timedelta(days=i), duration=600.0)
            for i in range(5)
        ],
    )
    by_id = {r.canonical_id for r in rows}
    assert len(by_id) == 5  # strength sessions on different days never merge

    _login(client)
    first = client.get("/api/activities", params={"limit": 2}).json()
    assert len(first["items"]) == 2
    assert first["items"][0]["id"] == rows[4].canonical_id  # newest first
    assert first["next_cursor"] is not None

    second = client.get("/api/activities", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [i["id"] for i in second["items"]] == [rows[2].canonical_id, rows[1].canonical_id]
    assert second["next_cursor"] is not None

    third = client.get("/api/activities", params={"limit": 2, "cursor": second["next_cursor"]}).json()
    assert [i["id"] for i in third["items"]] == [rows[0].canonical_id]
    assert third["next_cursor"] is None


def test_activities_list_includes_cached_strain(client, session):
    today = date.today()
    (activity,) = _seed(
        session,
        Activity(
            source="concept2",
            external_id="c1",
            type="rower",
            start=datetime.combine(today, datetime.min.time()).astimezone(timezone.utc),
            duration=600.0,
        ),
    )
    session.add(
        DailyScore(
            date=today,
            strain_json=json.dumps(
                {
                    "value": 9.0,
                    "band": "light",
                    "components": [{"canonical_id": activity.canonical_id, "value": 9.0, "band": "light"}],
                    "explanation": "x",
                }
            ),
        )
    )
    session.commit()

    _login(client)
    resp = client.get("/api/activities")
    items = resp.json()["items"]
    assert items[0]["strain"]["value"] == 9.0


def test_activity_detail_includes_zones_and_note(client, session):
    today = date.today()
    (activity,) = _seed(
        session,
        Activity(
            source="garmin",
            external_id="g1",
            type="indoor_rowing",
            start=datetime.combine(today, datetime.min.time()).astimezone(timezone.utc),
            avg_hr=150,
            duration=600.0,
        ),
    )
    session.add(Note(date=today, text="felt good", rpe=6))
    session.commit()

    from catch.core.settings_store import update_settings

    update_settings(session, {"max_hr": 190})

    _login(client)
    resp = client.get(f"/api/activities/{activity.canonical_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "erg"
    assert body["local_date"] == today.isoformat()
    assert body["day_note"]["text"] == "felt good"
    assert len(body["zones_config"]["zones"]) == 5
    assert body["hr_zone"] == "UT1"  # 150/190 = 78.9%


def test_activity_detail_404_for_missing(client):
    _login(client)
    resp = client.get("/api/activities/999")
    assert resp.status_code == 404
