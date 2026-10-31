from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from catch.core.models import Activity, DailyScore, Note
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_activities_category_filter_erg(client, session):
    session.add(Activity(source="garmin", external_id="g1", type="indoor_rowing", start=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    session.add(Activity(source="garmin", external_id="g2", type="rowing_v2", start=datetime(2026, 1, 2, tzinfo=timezone.utc)))
    session.add(Activity(source="concept2", external_id="c1", type="rower", start=datetime(2026, 1, 3, tzinfo=timezone.utc)))
    session.commit()

    _login(client)
    resp = client.get("/api/activities", params={"category": "erg"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {i["external_id"] for i in items} == {"g1", "c1"}
    assert all(i["category"] == "erg" for i in items)


def test_activities_category_filter_on_water(client, session):
    session.add(Activity(source="garmin", external_id="g2", type="rowing_v2", start=datetime(2026, 1, 2, tzinfo=timezone.utc)))
    session.add(Activity(source="concept2", external_id="c2", type="water", start=datetime(2026, 1, 3, tzinfo=timezone.utc)))
    session.add(Activity(source="garmin", external_id="g3", type="indoor_rowing", start=datetime(2026, 1, 4, tzinfo=timezone.utc)))
    session.commit()

    _login(client)
    resp = client.get("/api/activities", params={"category": "on_water"})
    items = resp.json()["items"]
    assert {i["external_id"] for i in items} == {"g2", "c2"}


def test_activities_category_rejects_unknown(client):
    _login(client)
    resp = client.get("/api/activities", params={"category": "bogus"})
    assert resp.status_code == 400


def test_activities_excludes_linked_garmin_duplicate(client, session):
    c2 = Activity(source="concept2", external_id="c1", type="rower", start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    session.add(c2)
    session.commit()
    garmin = Activity(
        source="garmin",
        external_id="g1",
        type="indoor_rowing",
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        linked_activity_id=c2.id,
    )
    session.add(garmin)
    session.commit()

    _login(client)
    resp = client.get("/api/activities")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["source"] == "concept2"


def test_activities_pagination_cursor(client, session):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(5):
        session.add(Activity(source="garmin", external_id=f"g{i}", type="strength_training", start=base + timedelta(days=i)))
    session.commit()

    _login(client)
    first = client.get("/api/activities", params={"limit": 2}).json()
    assert len(first["items"]) == 2
    assert first["items"][0]["external_id"] == "g4"  # newest first
    assert first["next_cursor"] is not None

    second = client.get("/api/activities", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [i["external_id"] for i in second["items"]] == ["g2", "g1"]
    assert second["next_cursor"] is not None

    third = client.get("/api/activities", params={"limit": 2, "cursor": second["next_cursor"]}).json()
    assert [i["external_id"] for i in third["items"]] == ["g0"]
    assert third["next_cursor"] is None


def test_activities_list_includes_cached_strain(client, session):
    today = date.today()
    activity = Activity(
        source="concept2",
        external_id="c1",
        type="rower",
        start=datetime.combine(today, datetime.min.time()).astimezone(timezone.utc),
    )
    session.add(activity)
    session.commit()
    session.add(
        DailyScore(
            date=today,
            strain_json=json.dumps(
                {
                    "value": 9.0,
                    "band": "light",
                    "components": [{"activity_id": activity.id, "value": 9.0, "band": "light"}],
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
    activity = Activity(
        source="garmin",
        external_id="g1",
        type="indoor_rowing",
        start=datetime.combine(today, datetime.min.time()).astimezone(timezone.utc),
        avg_hr=150,
    )
    session.add(activity)
    session.commit()
    session.add(Note(date=today, text="felt good", rpe=6))
    session.commit()

    from catch.core.settings_store import update_settings

    update_settings(session, {"max_hr": 190})

    _login(client)
    resp = client.get(f"/api/activities/{activity.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "erg"
    assert body["local_date"] == today.isoformat()
    assert body["note"]["text"] == "felt good"
    assert len(body["zones"]["zones"]) == 5
    assert body["hr_zone"] == "UT1"  # 150/190 = 78.9%


def test_activity_detail_404_for_missing(client):
    _login(client)
    resp = client.get("/api/activities/999")
    assert resp.status_code == 404
