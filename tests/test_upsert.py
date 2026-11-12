from __future__ import annotations

from catch.core import tenant
from datetime import date, datetime, timezone

from sqlmodel import select

from catch.core.models import Activity, BodyComp, DailyWellness
from catch.sync.upsert import upsert_activity, upsert_body_comp, upsert_daily_wellness


def test_daily_wellness_merges_without_clobbering(session):
    day = date(2026, 1, 1)
    upsert_daily_wellness(session, day, resting_hr=50)
    upsert_daily_wellness(session, day, stress=20)
    row = session.get(DailyWellness, tenant.pk(day))
    assert row.resting_hr == 50
    assert row.stress == 20

    # Passing None for a field already set must not null it out.
    upsert_daily_wellness(session, day, resting_hr=None, sleep_score=90)
    row = session.get(DailyWellness, tenant.pk(day))
    assert row.resting_hr == 50
    assert row.sleep_score == 90

    assert session.exec(select(DailyWellness)).all() == [row]


def test_activity_upsert_is_idempotent(session):
    upsert_activity(session, "garmin", "123", type="rowing", duration=1800.0)
    upsert_activity(session, "garmin", "123", type="rowing", duration=1850.0, calories=300)

    rows = session.exec(select(Activity)).all()
    assert len(rows) == 1
    assert rows[0].duration == 1850.0
    assert rows[0].calories == 300


def test_body_comp_upsert_is_idempotent(session):
    ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    upsert_body_comp(session, "withings", "grp1", ts=ts, weight_kg=72.4)
    upsert_body_comp(session, "withings", "grp1", ts=ts, fat_pct=18.2)

    rows = session.exec(select(BodyComp)).all()
    assert len(rows) == 1
    assert rows[0].weight_kg == 72.4
    assert rows[0].fat_pct == 18.2
