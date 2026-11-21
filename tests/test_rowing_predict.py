"""Session 32: which performances feed the 2k estimate (catch/sync/rowing_predict.py) and how it is reported."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from catch.core import localtime
from catch.core.models import Activity, CanonicalActivity
from catch.core.settings_store import get_settings, update_settings
from catch.sync import rowing_predict
from catch.sync.matching import run_matching

UTC = timezone.utc


def _now():
    return datetime.now(UTC).replace(microsecond=0)


def row(session, ext, days_ago, distance, seconds, avg_hr=None, workout_type="JustRow", raw=None):
    session.add(Activity(source="concept2", external_id=ext, type="rower", start=_now() - timedelta(days=days_ago), duration=seconds,
                         distance=distance, avg_hr=avg_hr, workout_type=workout_type, raw_json=json.dumps(raw or {})))
    session.commit()


def test_steady_rows_never_count_and_hard_rows_do(session):
    localtime.set_preferences(session, home="Europe/London")
    update_settings(session, {"max_hr": 195})
    row(session, "ut2", 3, 10000, 10000 / 500 * 125.0, avg_hr=140)  # 72 % of max: steady
    row(session, "hard5k", 6, 5000, 5000 / 500 * (100.0 + 5 * 1.321928), avg_hr=180)  # 92 %: implies a 6:40 (400 s)
    run_matching(session)
    est = rowing_predict.estimate_2k(session, get_settings(session))
    assert [c["label"] for c in est["components"]] == ["5000 m row"]
    assert est["predicted_time_s"] == pytest.approx(400.0, abs=0.5)
    assert est["measured_2k"] is None  # nothing measured: the estimate never pretends to be one


def test_untyped_results_with_rest_and_excluded_workouts_never_count(session):
    localtime.set_preferences(session, home="Europe/London")
    update_settings(session, {"max_hr": 195})
    row(session, "rest", 2, 4000, 1000.0, avg_hr=185, workout_type="unknown", raw={"rest_time": 1200})
    row(session, "ints", 2, 4000, 900.0, avg_hr=185, workout_type="FixedDistanceInterval")
    row(session, "excluded", 4, 2000, 400.0, avg_hr=185)
    run_matching(session)
    c = session.exec(select(Activity).where(Activity.external_id == "excluded")).first()
    canonical = session.get(CanonicalActivity, c.canonical_id)
    canonical.overrides_json = json.dumps({"exclude_from_totals": True})
    session.add(canonical)
    session.commit()
    rowing_predict.invalidate(session)
    est = rowing_predict.estimate_2k(session, get_settings(session))
    assert est["confidence"] == "insufficient_data" and est["components"] == []


def test_a_confirmed_2k_test_is_reported_as_measured_beside_the_estimate(session):
    localtime.set_preferences(session, home="Europe/London")
    row(session, "test", 10, 2000, 412.3, avg_hr=None, workout_type="FixedDistanceSplits")
    run_matching(session)
    c = session.exec(select(Activity).where(Activity.external_id == "test")).first()
    canonical = session.get(CanonicalActivity, c.canonical_id)
    canonical.overrides_json = json.dumps({"tags": ["test"], "test_type": "2000m"})
    canonical.category = "erg"
    session.add(canonical)
    session.commit()
    rowing_predict.invalidate(session)
    est = rowing_predict.estimate_2k(session, get_settings(session))
    assert est["measured_2k"]["latest"]["time_s"] == 412.3
    assert est["kind"] == "estimate" and est["predicted_time_s"] == pytest.approx(412.3)
    assert est["components"][0]["effort"] == "declared"


def test_the_threshold_for_an_old_session_uses_only_what_was_known_by_then(session):
    localtime.set_preferences(session, home="Europe/London")
    update_settings(session, {"max_hr": 195})
    row(session, "old", 100, 2000, 440.0, avg_hr=185)
    row(session, "new", 5, 2000, 400.0, avg_hr=185)
    run_matching(session)
    s = get_settings(session)
    then = rowing_predict.estimate_2k(session, s, before=_now() - timedelta(days=50))
    now = rowing_predict.estimate_2k(session, s)
    assert then["predicted_time_s"] == pytest.approx(440.0)
    assert now["predicted_time_s"] == pytest.approx(400.0)
    assert rowing_predict.rowing_watts_2k(session, s, before=_now() - timedelta(days=50)) < rowing_predict.rowing_watts_2k(session, s)


def test_the_api_says_estimate_and_ranges_in_seconds(client, session):
    assert client.post("/api/login", json={"password": "correct-horse-battery-staple"}).status_code == 200
    update_settings(session, {"max_hr": 195})
    row(session, "a", 3, 2000, 400.0, avg_hr=185)
    out = client.get("/api/predict/2k").json()
    assert out["kind"] == "estimate" and out["confidence"] in ("moderate", "high", "low")
    lo, hi = out["range_s"]
    assert lo < out["predicted_time_s"] < hi and hi - lo < 30
    assert "not a measured result" in out["explanation"]
