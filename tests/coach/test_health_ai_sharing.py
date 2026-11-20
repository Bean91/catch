"""Session 30: the Health data page tells people their Apple Health / Health Connect imports reach the AI coach only if they allowed
that category in AI sharing. Imported rows are ordinary workout/wellness rows, so the existing category gate must cover them — run
here with the REAL rules (the suite default allows everything)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from catch.coach import ai_sharing, tools
from catch.core.principal import ATHLETE
from catch.sync import wellness_readings
from catch.sync.upsert import upsert_activity

pytestmark = pytest.mark.real_ai_sharing


def _via(name, session, args=None):
    return tools.call_tool(session, name, args or {}, ctx={"principal": ATHLETE, "via": "ai_coach"})


def _import(session):
    start = datetime.now(timezone.utc) - timedelta(days=1)
    upsert_activity(session, "apple_health", "w-ai", type="rowingMachine", start=start, duration=2400.0, distance=8123.0)
    from catch.sync import matching

    matching.run_matching(session)  # resolves the canonical activity the way an import does
    day = date.today() - timedelta(days=1)
    wellness_readings.record_reading(session, day, "apple_health", "resting_hr", 51)
    wellness_readings.resolve_days(session, [day])


def test_imported_workouts_and_wellness_stay_out_of_the_ai_until_those_categories_are_on(session):
    _import(session)
    assert _via("list_workouts", session)["unavailable"] is True
    assert _via("get_today", session)["unavailable"] is True
    ai_sharing.update(session, acknowledge=True, categories={"workouts": True})
    out = _via("list_workouts", session)
    assert "unavailable" not in out and "8123" in str(out)  # on: the imported workout is there
    assert _via("get_today", session)["unavailable"] is True  # wellness is its own switch and is still off
    ai_sharing.update(session, acknowledge=False, categories={"workouts": False})
    assert _via("list_workouts", session)["unavailable"] is True


def test_the_workouts_category_text_names_the_health_platforms():
    text = ai_sharing.CATEGORIES["workouts"]["description"]
    assert "Apple Health" in text and "Health Connect" in text
