from __future__ import annotations

from datetime import timedelta

from conftest import TEST_PASSWORD

from catch.analytics.planning import week_start
from catch.core.models import CanonicalActivity
from catch.sync import planning as sp

MON = week_start(sp.today())


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _d(offset: int) -> str:
    return (MON + timedelta(days=offset)).isoformat()


def test_all_routes_require_auth(client):
    for method, path in (
        ("get", f"/api/calendar?from={_d(0)}&to={_d(6)}"),
        ("get", "/api/calendar/week-summary"),
        ("post", "/api/planned"),
        ("get", "/api/events/upcoming"),
        ("get", "/api/events"),
        ("get", "/api/phases"),
        ("post", "/api/phases"),
    ):
        assert getattr(client, method)(path).status_code == 401, path


def test_planned_workout_lifecycle(client):
    _login(client)
    res = client.post("/api/planned", json={"date": _d(1), "session_type": "erg", "duration_min": 60, "target_zone": "UT2", "title": "Steady"})
    assert res.status_code == 200
    pid = res.json()["planned"][0]["id"]
    assert client.patch(f"/api/planned/{pid}", json={"duration_min": 75}).json()["planned"][0]["duration_min"] == 75
    moved = client.post(f"/api/planned/{pid}/move", json={"date": _d(3)}).json()
    assert moved["date"] == _d(3)
    cal = client.get(f"/api/calendar?from={_d(0)}&to={_d(6)}").json()
    assert [p["title"] for d in cal["days"] for p in d["planned"]] == ["Steady"]
    assert client.delete(f"/api/planned/{pid}").json() == {"deleted": 1}
    assert client.get(f"/api/planned/{pid}").status_code == 404


def test_validation_errors_are_422_and_unknown_ids_404(client):
    _login(client)
    assert client.post("/api/planned", json={"date": _d(0), "session_type": "swim"}).status_code == 422
    assert client.post("/api/planned", json={"date": _d(0), "session_type": "erg", "target_zone": "Z9"}).status_code == 422
    assert client.patch("/api/planned/999", json={"title": "x"}).status_code == 404
    assert client.patch("/api/planned/999", json={"bogus": 1}).status_code in (404, 422)
    assert client.get(f"/api/calendar?from={_d(6)}&to={_d(0)}").status_code == 422
    assert client.get(f"/api/calendar?from={_d(0)}&to={_d(200)}").status_code == 422
    assert client.get("/api/events/999").status_code == 404


def test_repeat_creates_a_series_with_scoped_delete(client):
    _login(client)
    res = client.post("/api/planned", json={"date": _d(0), "session_type": "erg", "repeat": {"weekdays": [0, 2], "count": 6}}).json()["planned"]
    assert len(res) == 6 and len({r["series_id"] for r in res}) == 1
    assert client.delete(f"/api/planned/{res[2]['id']}?scope=this_and_following").json() == {"deleted": 4}
    assert client.post("/api/planned", json={"date": _d(0), "session_type": "erg", "repeat": {"weekdays": [0]}}).status_code == 422


def test_link_unlink_and_one_to_one(client, session):
    _login(client)
    canon = CanonicalActivity(start=sp._now(), duration=3600.0, sport_family="rowing", category="erg")
    session.add(canon)
    session.commit()
    a = client.post("/api/planned", json={"date": sp.today().isoformat(), "session_type": "erg"}).json()["planned"][0]["id"]
    b = client.post("/api/planned", json={"date": sp.today().isoformat(), "session_type": "erg"}).json()["planned"][0]["id"]
    linked = client.post(f"/api/planned/{a}/link", json={"canonical_id": canon.id}).json()
    assert linked["display_status"] == "linked"
    assert client.post(f"/api/planned/{b}/link", json={"canonical_id": canon.id}).status_code == 422
    assert client.post(f"/api/planned/{a}/unlink").json()["display_status"] == "planned"
    assert client.post(f"/api/planned/{b}/link", json={"canonical_id": 9999}).status_code == 404
    assert client.post(f"/api/planned/{b}/skip").json()["display_status"] == "skipped"
    assert client.post(f"/api/planned/{b}/unskip").json()["display_status"] == "planned"


def test_events_crud_upcoming_and_route_order(client):
    _login(client)
    soon = client.post("/api/events", json={"name": "Nationals", "date": _d(20), "type": "race", "priority": "A", "location": "Henley", "goals": "Top 8", "distance": "2000m", "goal_time": "6:45"}).json()
    assert soon["days_to_go"] == 20 + (MON - sp.today()).days
    client.post("/api/events", json={"name": "Club", "date": _d(10), "type": "race", "priority": "C"})
    assert [e["name"] for e in client.get("/api/events/upcoming").json()["events"]] == ["Club", "Nationals"]
    overview = client.get(f"/api/events/{soon['id']}").json()
    assert overview["event"]["location"] == "Henley" and overview["event"]["goals"] == "Top 8"
    assert client.patch(f"/api/events/{soon['id']}", json={"date": _d(21), "goals": None}).json()["goals"] is None
    assert client.post("/api/events", json={"name": "x", "date": _d(1), "type": "regatta"}).status_code == 422
    assert client.delete(f"/api/events/{soon['id']}").json() == {"ok": True}
    assert client.get(f"/api/events/{soon['id']}").status_code == 404


def test_event_projection_endpoint_is_honest_when_empty(client):
    _login(client)
    ev = client.post("/api/events", json={"name": "2k", "date": _d(30), "type": "2k_test", "distance": "2000m"}).json()
    out = client.get(f"/api/events/{ev['id']}/projection").json()
    assert out["available"] is False and out["assumptions"] and out["reason"]


def test_phase_lifecycle_overlap_and_approval(client):
    _login(client)
    base = {"kind": "general_prep", "name": "Base", "start_date": _d(0), "end_date": _d(27), "target_minutes_per_week": 360, "target_zone_pct": {"UT2": {"min": 70}}}
    ph = client.post("/api/phases", json=base).json()
    assert ph["coach_approved"] is False
    assert client.post("/api/phases", json={**base, "name": "B", "start_date": _d(20), "end_date": _d(40)}).status_code == 422
    assert client.post("/api/phases", json={**base, "kind": "peak", "start_date": _d(50), "end_date": _d(60)}).status_code == 422
    approved = client.post(f"/api/phases/{ph['id']}/approve", json={"approved_by": "Coach", "note": "ok"}).json()
    assert approved["coach_approved"] and approved["coach_approved_by"] == "Coach" and approved["edited_since_approval"] is False
    client.post("/api/planned", json={"date": _d(2), "session_type": "erg", "duration_min": 60})
    assert client.get("/api/phases").json()["phases"][0]["edited_since_approval"] is True
    assert client.get(f"/api/calendar/phase?date={_d(5)}").json()["targets"]["minutes"] == 360
    assert client.post(f"/api/phases/{ph['id']}/unapprove").json()["coach_approved"] is False
    assert client.delete(f"/api/phases/{ph['id']}").json() == {"ok": True}


def test_week_summary_endpoint(client):
    _login(client)
    client.post("/api/planned", json={"date": _d(0), "session_type": "erg", "duration_min": 60, "target_zone": "UT2"})
    out = client.get(f"/api/calendar/week-summary?week_start={_d(3)}").json()
    assert out["week_start"] == _d(0) and out["planned"]["minutes"] == 60
    assert any(r["metric"] == "minutes" for r in out["comparison"])


def test_legacy_memory_event_routes_still_work_and_fix_string_dates(client):
    _login(client)
    created = client.post("/api/coach/memory/events", json={"name": "Old", "date": _d(5), "type": "race"}).json()
    assert created["id"] and created["name"] == "Old"
    edited = client.put(f"/api/coach/memory/events/{created['id']}", json={"date": _d(8), "goal_time": "6:40"}).json()
    assert edited["date"] == _d(8) and edited["goal_time"] == "6:40"
    assert client.put(f"/api/coach/memory/events/{created['id']}", json={"date": "not-a-date"}).status_code == 422
    assert client.delete(f"/api/coach/memory/event:{created['id']}").status_code in (200, 204)
