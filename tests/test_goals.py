"""Session 36: measurable goals (catch/analytics/goals.py, catch/sync/goals.py, /api/goals, the coach's set_goal)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from catch.analytics import goals as g
from catch.core import localtime
from catch.core.models import Activity, Goal
from catch.sync.matching import run_matching
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _row(session, ext, day, minutes, distance, type_="indoor_rowing", source="garmin", **kw):
    a = Activity(source=source, external_id=ext, type=type_, start=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10),
                 duration=minutes * 60, distance=distance, **kw)
    session.add(a)
    session.commit()
    run_matching(session)
    return a


def test_validation():
    with pytest.raises(ValueError):
        g.validate({"kind": "distance_total", "target_value": 1000})  # no window
    with pytest.raises(ValueError):
        g.validate({"kind": "target_split", "target_value": 105, "start_date": date(2026, 1, 1), "end_date": date(2026, 2, 1)})  # no distance
    with pytest.raises(ValueError):
        g.validate({"kind": "weekly_volume", "target_value": 300, "start_date": date(2026, 1, 1), "end_date": date(2026, 1, 3)})
    g.validate({"kind": "text", "text": "Row a sub-7 2k"})


def test_distance_goal_progress_is_capped_and_respects_the_window(session):
    today = localtime.today(session)
    start = today - timedelta(days=10)
    _row(session, "in1", start + timedelta(days=1), 60, 12000)
    _row(session, "in2", start + timedelta(days=2), 60, 12000)
    _row(session, "out", start - timedelta(days=2), 60, 50000)  # before the window: never counts
    from catch.sync import goals

    row = goals.create(session, {"kind": "distance_total", "sport": "rowing", "target_value": 20000, "start_date": start, "end_date": today + timedelta(days=5)})
    d = goals.goal_dict(session, row, today)
    assert d["text"] == "20 km"
    assert d["progress"]["current"] == 24000 and d["progress"]["pct"] == 100.0 and d["progress"]["achieved"] is True


def test_weekly_goal_counts_weeks_not_a_running_debt(session):
    today = localtime.today(session)
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=2)
    _row(session, "w1", start + timedelta(days=1), 200, 40000)
    _row(session, "w2", start + timedelta(days=8), 100, 20000)
    from catch.sync import goals

    row = goals.create(session, {"kind": "weekly_volume", "target_value": 150, "start_date": start, "end_date": monday + timedelta(days=13)})
    p = goals.goal_dict(session, row, today)["progress"]
    assert p["weeks_finished"] == 2 and p["weeks_met"] == 1
    assert [w["met"] for w in p["weeks"][:2]] == [True, False]
    assert "streak" not in str(p).lower()


def test_split_goal_reached_by_a_qualifying_effort(session):
    today = localtime.today(session)
    _row(session, "c2a", today - timedelta(days=5), 7.1, 2000, type_="rower", source="concept2", workout_type="JustRow")
    from catch.sync import goals

    row = goals.create(session, {"kind": "target_split", "target_value": 107.0, "params": {"distance_m": 2000}, "start_date": today - timedelta(days=30), "end_date": today + timedelta(days=30)})
    p = goals.goal_dict(session, row, today)["progress"]
    assert p["current"] == pytest.approx(106.5) and p["achieved"] is True and p["achieved_ref"].startswith("/workouts/")


def test_api_crud_partial_update_and_status(client, session):
    _login(client)
    today = date.today()
    created = client.post("/api/goals", json={"kind": "workout_count", "target_value": 12, "start_date": today.isoformat(), "end_date": (today + timedelta(days=30)).isoformat(), "text": "12 sessions this month"}).json()
    gid = created["id"]
    upd = client.patch(f"/api/goals/{gid}", json={"text": "Twelve sessions"}).json()
    assert upd["target_value"] == 12 and upd["kind"] == "workout_count"  # untouched fields survive
    done = client.patch(f"/api/goals/{gid}", json={"status": "done"}).json()
    assert done["completed_at"] is not None and done["progress"]["state"] == "done"
    assert client.get("/api/goals", params={"view": "active"}).json()["goals"] == []
    assert len(client.get("/api/goals", params={"view": "history"}).json()["goals"]) == 1
    assert client.patch(f"/api/goals/{gid}", json={"status": "nope"}).status_code == 422
    assert client.patch("/api/goals/99999", json={"text": "x"}).status_code == 404
    assert client.delete(f"/api/goals/{gid}").status_code == 200


def test_coach_set_goal_updates_only_what_it_was_given(session):
    from catch.coach import tools

    created = tools.call_tool(session, "set_goal", {"text": "Sub-7 2k", "target_date": "2027-03-01", "confirm": True})
    gid = int(created["result"]["id"]) if "result" in created else int(created["id"])
    tools.call_tool(session, "set_goal", {"id": gid, "status": "done", "confirm": True})
    row = session.get(Goal, gid)
    assert row.text == "Sub-7 2k" and row.target_date == date(2027, 3, 1) and row.status == "done"
