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


# --- Session 36 follow-up: narrowing a watch's laps to the planned work reps -------------------------------------------

_WORK4 = pc.expand_planned([{"reps": 4, "work_min": 4, "rest_min": 2, "split_s": 110}])
_WARM_WORK_COOL = pc.expand_planned([{"kind": "warmup", "work_min": 10}, {"reps": 4, "work_min": 4, "rest_min": 2}, {"kind": "cooldown", "work_min": 8}])


def _lap(seconds: float, intensity: str | None = None, distance: float | None = None) -> dict:
    lap = {"duration_s": seconds}
    if intensity:
        lap["intensity"] = intensity
    if distance is not None:
        lap["distance_m"] = distance
    return lap


def _work(reps):
    return [r for r in reps if r["kind"] == "work"]


def test_lap_counts_that_agree_pair_in_order():
    laps = [_lap(240)] * 4
    assert pc.select_work_laps(laps, _work(_WORK4), _WORK4)[1] == "order"


def test_laps_with_the_watchs_own_intensity_pair_by_it():
    laps = [_lap(600, "warmup")] + [_lap(240, "active"), _lap(120, "rest")] * 4 + [_lap(480, "cooldown")]
    chosen, method, reason = pc.select_work_laps(laps, _work(_WORK4), _WORK4)
    assert method == "intensity" and len(chosen) == 4 and all(lap["intensity"] == "active" for lap in chosen) and reason is None


def test_alternating_rest_laps_are_still_recognised():
    laps = [_lap(241), _lap(118), _lap(239), _lap(121), _lap(240), _lap(119), _lap(242)]
    chosen, method, _ = pc.select_work_laps(laps, _work(_WORK4), _WORK4)
    assert method == "alternating_rest" and [lap["duration_s"] for lap in chosen] == [241, 239, 240, 242]


def test_one_fitting_choice_of_laps_pairs_by_length():
    # A warm-up, four work laps (one an auto-lap split into two: no fit), an extra lap pressed at the end, a cool-down.
    laps = [_lap(612), _lap(238), _lap(130), _lap(243), _lap(118), _lap(236), _lap(125), _lap(244), _lap(470)]
    chosen, method, _ = pc.select_work_laps(laps, _work(_WORK4), _WORK4)
    assert method == "lengths" and [lap["duration_s"] for lap in chosen] == [238, 243, 236, 244]
    dist = pc.expand_planned([{"reps": 3, "work_m": 1000, "rest_min": 3}])
    laps = [_lap(400, distance=1500), _lap(220, distance=1004), _lap(180, distance=210), _lap(222, distance=998), _lap(180, distance=200), _lap(219, distance=1001)]
    chosen, method, _ = pc.select_work_laps(laps, _work(dist), dist)
    assert method == "lengths" and [lap["distance_m"] for lap in chosen] == [1004, 998, 1001]


def test_several_or_no_fitting_choices_stay_unpaired_with_the_reason():
    several = [_lap(240)] * 6  # any 4 of 6 equal laps fit: which four is unknown
    chosen, method, reason = pc.select_work_laps(several, _work(_WORK4), _WORK4)
    assert method is None and chosen == several and "more than one" in reason
    none = [_lap(100)] * 6
    assert "none of the ways" in pc.select_work_laps(none, _work(_WORK4), _WORK4)[2]
    fewer = [_lap(240)] * 3
    assert "3 laps for 4 planned" in pc.select_work_laps(fewer, _work(_WORK4), _WORK4)[2]
    result = pc.compare({"structure": [{"reps": 4, "work_min": 4, "rest_min": 2, "split_s": 110}]}, [{"duration_s": 240}] * 6, {},
                        reps_source="laps", pairing_reason=reason)
    assert result["mode"] != "per_rep" and "more than one" in result["reason"]


def test_laps_pair_through_the_api(client, session):
    _login(client)
    day = localtime.today(session) - timedelta(days=2)
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=7)
    laps = [{"offset_s": 0, "duration_s": 600, "intensity": "warmup"}]
    t = 600
    for _ in range(4):
        laps += [{"offset_s": t, "duration_s": 240, "intensity": "active", "avg_hr": 165.0}, {"offset_s": t + 240, "duration_s": 120, "intensity": "rest"}]
        t += 360
    a = Activity(source="garmin", external_id="g-laps", type="indoor_rowing", start=start, duration=float(t), laps_json=json.dumps(laps))
    session.add(a)
    session.commit()
    run_matching(session)
    session.refresh(a)
    planned = client.post("/api/planned", json={
        "date": day.isoformat(), "session_type": "erg", "title": "4 x 4 min",
        "structure": [{"reps": 4, "work_min": 4, "rest_min": 2, "hr_min": 150, "hr_max": 160}],
    }).json()["planned"][0]
    client.post(f"/api/planned/{planned['id']}/link", json={"canonical_id": a.canonical_id})
    cmp = client.get(f"/api/planned/{planned['id']}/comparison").json()["comparison"]
    assert cmp["mode"] == "per_rep" and cmp["reps_source"] == "laps" and cmp["pairing"] == "intensity"
    assert {m["metric"]: m for m in cmp["reps"][0]["metrics"]}["hr"]["status"] == "above"
