"""Session 32 (docs/performance.md): statement-count budgets on a seeded history, so an N+1 can't creep back in. The numbers measured
with scripts/perf_personal.py on three years were 21 / 3 / 46 statements; the budgets leave room for small changes but not for a
query per row or per day (which is what /api/today, the 2k estimate and every write used to do)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from catch.core import localtime
from catch.core.models import Activity, CheckIn, DailyWellness
from catch.core.settings_store import update_settings
from catch.sync import scoring
from catch.sync.matching import run_matching
from tests.conftest import TEST_PASSWORD

DAYS = 120


@pytest.fixture()
def seeded(client, session):
    localtime.set_preferences(session, home="Europe/London", follow=False)
    update_settings(session, {"max_hr": 190})
    start = localtime.today(session) - timedelta(days=DAYS)
    for i in range(DAYS + 1):
        day = start + timedelta(days=i)
        session.add(DailyWellness(date=day, resting_hr=50, hrv_rmssd=60 + i % 9, sleep_seconds=7 * 3600, steps=9000))
        session.add(CheckIn(date=day, soreness=2, stress=2, mood=4, sleep_quality=3))
        session.add(Activity(source="concept2", external_id=f"c{i}", type="rower", start=datetime(day.year, day.month, day.day, 7, tzinfo=timezone.utc),
                             duration=3600.0, distance=12000.0, avg_hr=150 + i % 30, workout_type="JustRow"))
    session.commit()
    run_matching(session)
    scoring.recompute_scores(session, full=True)
    assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 200
    return client


def statements(session, fn) -> int:
    count = [0]

    def cb(*_):
        count[0] += 1

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", cb)
    try:
        r = fn()
        assert r.status_code == 200, r.text
    finally:
        event.remove(engine, "before_cursor_execute", cb)
    return count[0]


@pytest.mark.parametrize("url, budget", [("/api/today", 40), ("/api/activities?limit=50", 8), ("/api/predict/2k", 20), ("/api/erg/results", 12),
                                         ("/api/training-intelligence/profile", 45)])
def test_reads_stay_within_their_statement_budget(seeded, session, url, budget):
    assert statements(session, lambda: seeded.get(url)) <= budget


def test_a_check_in_recomputes_a_few_days_not_the_whole_history(seeded, session):
    n = statements(session, lambda: seeded.post("/api/checkins", json={"date": date.today().isoformat(), "soreness": 3, "stress": 2, "mood": 4, "sleep_quality": 4}))
    assert n <= 80
