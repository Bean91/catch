"""Session 36: regression tests for bugs the audit found. Each fails on the code before the fix."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from catch.core.models import Activity, CanonicalActivity, PlannedWorkout
from catch.sync.matching import run_matching
from catch.sync.samples import store_samples
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _workout(session, ext: str, start: datetime, duration: float = 1800.0, distance: float | None = 6000.0) -> CanonicalActivity:
    a = Activity(source="garmin", external_id=ext, type="indoor_rowing", start=start, duration=duration, distance=distance)
    session.add(a)
    session.commit()
    run_matching(session)
    session.refresh(a)
    return session.get(CanonicalActivity, a.canonical_id)


def test_trends_volume_accepts_the_104_weeks_the_trends_page_asks_for(client, session):
    _login(client)
    resp = client.get("/api/trends/volume", params={"weeks": 104})
    assert resp.status_code == 200
    assert len(resp.json()) == 104


def test_bulk_tag_adds_to_existing_tags_and_keeps_the_test_tag(client, session):
    c = _workout(session, "b1", datetime.now(timezone.utc) - timedelta(days=2))
    c.overrides_json = json.dumps({"tags": ["test"], "test_type": "2000m"})
    session.add(c)
    session.commit()
    _login(client)
    resp = client.post("/api/activities/bulk", json={"canonical_ids": [c.id], "tags_add": ["race"]})
    assert resp.status_code == 200
    session.expire_all()
    tags = json.loads(session.get(CanonicalActivity, c.id).overrides_json)["tags"]
    assert tags == ["test", "race"]
    client.post("/api/activities/bulk", json={"canonical_ids": [c.id], "tags_remove": ["race"]})
    session.expire_all()
    assert json.loads(session.get(CanonicalActivity, c.id).overrides_json)["tags"] == ["test"]


def test_bulk_edit_validates_like_a_single_edit(client, session):
    c = _workout(session, "b2", datetime.now(timezone.utc) - timedelta(days=2))
    _login(client)
    assert client.post("/api/activities/bulk", json={"canonical_ids": [c.id], "patch": {"rpe": 42}}).status_code == 422
    assert client.post("/api/activities/bulk", json={"canonical_ids": [c.id], "patch": {"tags": ["x"]}}).status_code == 422


def test_clearing_a_planned_title_falls_back_to_the_default_instead_of_500(client, session):
    _login(client)
    created = client.post("/api/planned", json={"date": date.today().isoformat(), "session_type": "erg", "title": "Tempo"}).json()
    pid = created["planned"][0]["id"]
    resp = client.patch(f"/api/planned/{pid}", json={"title": None})
    assert resp.status_code == 200
    session.expire_all()
    assert session.get(PlannedWorkout, pid).title  # never empty


def test_samples_break_the_line_at_a_dropout_and_never_bridge_it(client, session):
    a = Activity(source="garmin", external_id="s1", type="indoor_rowing", start=datetime.now(timezone.utc), duration=300.0)
    session.add(a)
    session.commit()
    hr = [140.0] * 100 + [None] * 60 + [150.0] * 140
    store_samples(session, a.id, start=a.start, hr=hr, power=[None] * 300, cadence=[None] * 300)
    run_matching(session)
    session.refresh(a)
    _login(client)
    body = client.get(f"/api/activities/{a.canonical_id}/samples", params={"points": 50}).json()
    assert body["gaps"] == 1
    gap_points = [p for p in body["points"] if 100 <= p["elapsed_s"] < 160]
    assert gap_points and all(p["hr"] is None for p in gap_points)


def test_power_only_recording_has_a_chart(client, session):
    a = Activity(source="garmin", external_id="s2", type="indoor_cycling", start=datetime.now(timezone.utc), duration=120.0)
    session.add(a)
    session.commit()
    store_samples(session, a.id, start=a.start, hr=[None] * 120, power=[200.0] * 120, cadence=[85.0] * 120)
    run_matching(session)
    session.refresh(a)
    _login(client)
    body = client.get(f"/api/activities/{a.canonical_id}/samples").json()
    assert body["has_data"] is True and body["has_hr"] is False and body["has_power"] is True
    assert body["avg_hr"] is None


def test_adjacent_day_link_is_shown_under_the_plan(client, session):
    from catch.core import localtime

    _login(client)
    day = localtime.today(session) - timedelta(days=3)
    created = client.post("/api/planned", json={"date": day.isoformat(), "session_type": "erg", "title": "Steady"}).json()
    pid = created["planned"][0]["id"]
    c = _workout(session, "adj", datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=12))
    assert client.post(f"/api/planned/{pid}/link", json={"canonical_id": c.id}).status_code == 200
    cal = client.get("/api/calendar", params={"from": day.isoformat(), "to": day.isoformat()}).json()
    plan = cal["days"][0]["planned"][0]
    assert plan["linked_completed"]["id"] == c.id
