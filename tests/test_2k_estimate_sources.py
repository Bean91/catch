"""Where the 2k estimate's evidence comes from (2026-11-22): interval pieces and Concept2 interval results count (once per workout),
heart rate is the workout's own when the Concept2 row has none, and the Today card's erg piece is a rowing erg only."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import select

from catch.core.models import Activity, CanonicalActivity, PieceInterval
from catch.core.settings_store import update_settings
from catch.sync import rowing_predict
from catch.sync.piece_intervals import build_intervals_from_concept2, create_interval_piece
from conftest import TEST_PASSWORD

WORKOUT = json.loads((Path(__file__).parent / "fixtures" / "concept2" / "result_102_detail.json").read_text())["data"]["workout"]
START = datetime.now(timezone.utc) - timedelta(days=5)


def _canonical(session, **kw) -> CanonicalActivity:
    c = CanonicalActivity(sport_family="rowing", start=START, category="erg", **kw)
    session.add(c)
    session.commit()
    return c


def _c2(session, c, ext="102", **kw) -> Activity:
    fields = {"type": "rower", "workout_type": "FixedDistanceInterval", "distance": 2000.0, "duration": 600.0, "intervals_json": json.dumps(WORKOUT), **kw}
    a = Activity(source="concept2", external_id=ext, start=START, canonical_id=c.id, **fields)
    session.add(a)
    session.commit()
    return a


def _estimate(session):
    rowing_predict.invalidate(session)
    return rowing_predict.estimate_2k(session, {"max_hr": 190})


def test_a_concept2_interval_result_counts_when_its_peak_heart_rate_shows_hard_work(session):
    c = _canonical(session, max_hr=180.0, avg_hr=150.0)  # the watch's HR, on the workout
    _c2(session, c)
    r = _estimate(session)
    assert [comp["kind"] for comp in r["components"]] == ["intervals"]
    assert r["components"][0]["label"] == "Intervals: 4 × 500 m" and r["components"][0]["effort"] == "hr_verified"
    assert 420 < r["predicted_time_s"] < 445  # 4 x 500 m at 1:45.0 with a minute's rest: about a 7:12 2k


def test_an_easy_interval_session_does_not_count(session):
    c = _canonical(session, max_hr=150.0)
    _c2(session, c)
    assert _estimate(session)["components"] == []


def test_a_piece_imported_from_that_result_counts_once(session):
    c = _canonical(session, max_hr=180.0)
    a = _c2(session, c)
    build_intervals_from_concept2(session, c.id, a.id)
    r = _estimate(session)
    assert len(r["components"]) == 1 and r["components"][0]["effort"] == "declared"


def test_a_typed_interval_piece_counts(session):
    c = _canonical(session)
    rows = [{"target_type": "distance", "work_distance_m": 1000, "work_duration_s": 222.0, "rest_duration_s": 180 if i < 2 else None} for i in range(3)]
    piece, validation = create_interval_piece(session, c.id, rows)
    assert piece is not None, validation
    r = _estimate(session)
    assert r["components"][0]["label"] == "Intervals: 3 × 1,000 m" and r["components"][0]["kind"] == "intervals"


def test_editing_an_interval_changes_the_estimate_in_the_same_session(session):
    c = _canonical(session)
    rows = [{"target_type": "distance", "work_distance_m": 1000, "work_duration_s": 222.0, "rest_duration_s": 180 if i < 2 else None} for i in range(3)]
    create_interval_piece(session, c.id, rows)
    rowing_predict.invalidate(session)
    before = rowing_predict.estimate_2k(session, {"max_hr": 190})["predicted_time_s"]
    for r in session.exec(select(PieceInterval)).all():
        r.work_duration_s = 216.0
        session.add(r)
    session.commit()
    assert rowing_predict.estimate_2k(session, {"max_hr": 190})["predicted_time_s"] < before  # no stale cache


def test_a_continuous_row_uses_the_workouts_heart_rate_when_the_concept2_row_has_none(session):
    c = _canonical(session, avg_hr=172.0)
    _c2(session, c, workout_type="JustRow", intervals_json=None, distance=5000.0, duration=1140.0)
    r = _estimate(session)
    assert r["components"][0]["effort"] == "hr_verified"


def test_the_history_chart_leaves_out_an_impossible_effort(session):
    c = _canonical(session, avg_hr=172.0)
    _c2(session, c, workout_type="JustRow", intervals_json=None, distance=3046.0, duration=2640.0)
    assert rowing_predict.evidence(session, {"max_hr": 190})  # it is evidence-shaped...
    assert rowing_predict.implied_2k_history(session, {"max_hr": 190}) == []  # ...but not a point anyone should see
    assert _estimate(session)["excluded"][0]["distance_m"] == 3046.0


def test_the_today_card_shows_the_latest_rowing_erg_piece_not_a_bikeerg(client, session):
    update_settings(session, {"max_hr": 190})
    row = _c2(session, _canonical(session), ext="r1", workout_type="JustRow", intervals_json=None)
    bike = Activity(source="concept2", external_id="b1", type="bike", workout_type="JustRow", start=START + timedelta(days=1), distance=42195.0, duration=5374.0)
    session.add(bike)
    session.commit()
    client.post("/api/login", json={"password": TEST_PASSWORD})
    assert client.get("/api/today").json()["latest_erg"]["id"] == row.id
