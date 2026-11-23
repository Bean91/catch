"""Session 36: Foster monotony/strain and the load-history read (catch/analytics/load.py, catch/sync/load_history.py)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from catch.analytics.load import weekly_monotony_strain
from catch.core import localtime
from catch.core.models import Activity, DailyScore, PlannedWorkout
from catch.sync.matching import run_matching
from conftest import TEST_PASSWORD


def test_foster_monotony_and_strain():
    r = weekly_monotony_strain([100, 0, 100, 0, 100, 0, 100])
    assert r["load"] == 400
    assert r["monotony"] == pytest.approx((400 / 7) / 49.487, rel=1e-3)
    assert r["strain"] == pytest.approx(400 * r["monotony"])
    flat = weekly_monotony_strain([50] * 7)
    assert flat["monotony"] is None and "undefined" in flat["reason"]
    assert weekly_monotony_strain([0] * 7)["monotony"] is None


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_load_history_counts_once_excludes_steps_and_ignores_plans(client, session):
    today = localtime.today(session)
    monday = today - timedelta(days=today.weekday())
    last_week = monday - timedelta(weeks=1)
    for i in range(7):
        d = last_week + timedelta(days=i)
        strain = {"load": 120.0 if i % 2 == 0 else 20.0, "daily_activity": {"load": 20.0}}
        session.add(DailyScore(date=d, strain_json=json.dumps(strain), recovery_json=json.dumps({"value": 60 + i})))
    t = datetime.combine(last_week + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
    # A watch and a PM5 recording of the same row: matching merges them, and the week counts one session.
    session.add(Activity(source="garmin", external_id="w", type="indoor_rowing", start=t, duration=3600.0, distance=14000.0))
    session.add(Activity(source="concept2", external_id="c", type="rower", start=t + timedelta(seconds=20), duration=3580.0, distance=14000.0, workout_type="JustRow"))
    session.add(PlannedWorkout(date=last_week + timedelta(days=3), session_type="erg", title="Plan", duration_min=999))
    session.commit()
    run_matching(session)
    _login(client)
    body = client.get("/api/trends/load-history", params={"weeks": 6}).json()
    wk = next(w for w in body["weeks"] if w["week_start"] == last_week.isoformat())
    assert wk["sessions"] == 1 and wk["minutes"] == pytest.approx(60, abs=1)
    assert wk["load"] == pytest.approx(4 * 100.0)  # steps (20 a day) left out of training load
    assert wk["monotony"] is not None and wk["days_without_training"] == 6
    assert wk["avg_recovery"] == pytest.approx(63)
    assert client.get("/api/trends/load-history", params={"weeks": 200}).status_code == 422
