"""Session 36: planned targets against what was done (catch/analytics/plan_compare.py, catch/sync/plan_compare.py)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from catch.analytics import plan_compare as pc
from catch.core import localtime
from catch.core.models import Activity
from catch.sync.matching import run_matching
from conftest import TEST_PASSWORD


def _rep(**kw):
    return pc.actual_from_values(**kw)


def test_rows_only_for_targets_that_were_set():
    planned = {"structure": [{"reps": 2, "work_m": 500, "rest_min": 1, "split_s": 105}]}
    out = pc.compare(planned, [_rep(duration_s=104, distance_m=500), _rep(duration_s=107, distance_m=500)], _rep())
    assert out["mode"] == "per_rep"
    metrics = {m["metric"] for r in out["reps"] for m in r["metrics"]}
    assert metrics == {"distance_m", "split_s"}  # no watts/rate/hr rows: none were planned
    split = next(m for m in out["reps"][1]["metrics"] if m["metric"] == "split_s")
    assert split["delta"] == pytest.approx(2.0) and split["actual_basis"] == "derived"
    assert out["totals"] == []  # the plan had no total duration/distance


def test_ranges_report_below_in_range_above_and_no_verdict_on_single_values():
    planned = {"structure": [{"reps": 3, "work_min": 4, "rate_min": 20, "rate_max": 22, "hr_max": 160}]}
    reps = [_rep(duration_s=240, rate=19, hr=150), _rep(duration_s=240, rate=21, hr=165), _rep(duration_s=240, rate=23, hr=None)]
    out = pc.compare(planned, reps, _rep())
    rate = [next(m for m in r["metrics"] if m["metric"] == "rate")["status"] for r in out["reps"]]
    hr = [next(m for m in r["metrics"] if m["metric"] == "hr") for r in out["reps"]]
    assert rate == ["below", "in_range", "above"]
    assert [h["status"] for h in hr] == ["in_range", "above", None] and hr[2]["actual"] is None
    assert all("status" not in m for r in out["reps"] for m in r["metrics"] if m["metric"] == "duration_s")


def test_mismatched_rep_counts_fall_back_to_the_session_with_a_reason():
    planned = {"duration_min": 30, "structure": [{"reps": 4, "work_m": 500, "rest_min": 2, "split_s": 100}]}
    out = pc.compare(planned, [_rep(duration_s=100, distance_m=500)] * 3, _rep(duration_s=1700, distance_m=2000))
    assert out["mode"] == "whole" and out["reps"] == []
    assert "4 work reps" in out["reason"] and "3" in out["reason"]
    assert "whole-session average" in out["reason"]
    assert out["totals"][0]["delta"] == pytest.approx(-100)
    assert out["whole"] == []  # rep targets never compared with a session average that includes rest


def test_a_continuous_plan_compares_its_targets_with_the_whole_session():
    planned = {"structure": [{"reps": 1, "work_min": 60, "hr_max": 150, "rate_min": 18, "rate_max": 20}]}
    out = pc.compare(planned, [], _rep(duration_s=3600, hr=148, rate=19))
    assert out["mode"] == "whole" and out["reason"] is None
    assert {m["metric"]: m["status"] for m in out["whole"]} == {"rate": "in_range", "hr": "in_range"}


def test_warmup_and_cooldown_pair_only_when_the_recording_has_them_too():
    planned = {"structure": [{"reps": 1, "kind": "warmup", "work_min": 10}, {"reps": 2, "work_m": 1000}, {"reps": 1, "kind": "cooldown", "work_min": 5}]}
    two = pc.compare(planned, [_rep(distance_m=1000, duration_s=210)] * 2, _rep())
    assert [r["kind"] for r in two["reps"]] == ["work", "work"]
    four = pc.compare(planned, [_rep(duration_s=600), _rep(distance_m=1000), _rep(distance_m=1000), _rep(duration_s=300)], _rep())
    assert [r["kind"] for r in four["reps"]] == ["warmup", "work", "work", "cooldown"]


def test_no_targets_means_nothing_to_compare():
    out = pc.compare({"structure": []}, [], _rep(duration_s=600))
    assert out["mode"] == "none" and out["has_targets"] is False


# --- Through the API, with a real Concept2 interval result -----------------------------------------


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_planned_vs_done_with_concept2_intervals(client, session):
    _login(client)
    day = localtime.today(session) - timedelta(days=1)
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
    raw = {"intervals": [
        {"type": "distance", "distance": 500, "time": 1040, "rest_time": 600, "stroke_rate": 30},
        {"type": "distance", "distance": 500, "time": 1060, "rest_time": 600, "stroke_rate": 31},
    ]}
    a = Activity(source="concept2", external_id="c2-plan", type="rower", start=start, duration=210.0, distance=1000.0,
                 workout_type="FixedDistanceInterval", intervals_json=json.dumps(raw))
    session.add(a)
    session.commit()
    run_matching(session)
    session.refresh(a)

    planned = client.post("/api/planned", json={
        "date": day.isoformat(), "session_type": "erg", "title": "2 x 500m",
        "structure": [{"reps": 2, "work_m": 500, "rest_min": 1, "split_s": 105, "rate_min": 28, "rate_max": 30}],
    }).json()["planned"][0]
    # Before linking there is nothing to compare.
    assert client.get(f"/api/planned/{planned['id']}/comparison").json()["comparison"] is None
    cands = client.get(f"/api/planned/{planned['id']}/link-candidates").json()["candidates"]
    assert [c["id"] for c in cands] == [a.canonical_id] and cands[0]["days_from_plan"] == 0
    assert client.post(f"/api/planned/{planned['id']}/link", json={"canonical_id": a.canonical_id}).status_code == 200

    body = client.get(f"/api/planned/{planned['id']}/comparison").json()
    cmp = body["comparison"]
    assert cmp["mode"] == "per_rep" and cmp["reps_source"] == "concept2"
    rep2 = {m["metric"]: m for m in cmp["reps"][1]["metrics"]}
    assert rep2["split_s"]["actual"] == pytest.approx(106.0) and rep2["split_s"]["delta"] == pytest.approx(1.0)
    assert rep2["rate"]["status"] == "above"
    # The same comparison from the workout's side.
    via_workout = client.get(f"/api/activities/{a.canonical_id}/plan-comparison").json()
    assert via_workout["planned_id"] == planned["id"]


def test_plan_comparison_for_an_unlinked_workout(client, session):
    _login(client)
    a = Activity(source="garmin", external_id="g-unlinked", type="indoor_rowing", start=datetime.now(timezone.utc), duration=600.0)
    session.add(a)
    session.commit()
    run_matching(session)
    session.refresh(a)
    assert client.get(f"/api/activities/{a.canonical_id}/plan-comparison").json() == {"planned": None}
    assert client.get("/api/activities/999999/plan-comparison").status_code == 404
