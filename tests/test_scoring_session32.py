"""Session 32: daily scores end to end — the one-curve strain over realistic weeks, unmerged cross-provider duplicates, and the
incremental recompute producing exactly what a full one does."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlmodel import select

from catch.core import localtime, tenant
from catch.core.models import Activity, CheckIn, DailyScore, DailyWellness, Note
from catch.core.settings_store import get_settings, update_settings
from catch.sync import scoring
from catch.sync.matching import run_matching

UTC = timezone.utc
START = date(2026, 9, 1)


def at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def seed_weeks(session, weeks=6):
    """Rows most mornings, a hard piece on Saturdays, Sundays off, steps every day, check-ins and a weekly RPE note."""
    localtime.set_preferences(session, home="Europe/London", follow=False)
    update_settings(session, {"max_hr": 190})
    n = 0
    for i in range(weeks * 7):
        day = START + timedelta(days=i)
        session.add(DailyWellness(date=day, resting_hr=48 + i % 4, hrv_rmssd=60 + (i * 7) % 15, sleep_seconds=7 * 3600 + (i % 5) * 600,
                                  steps=6000 + (i * 1300) % 7000, active_kcal=300 + (i * 37) % 300))
        session.add(CheckIn(date=day, soreness=1 + i % 4, stress=2, mood=3 + i % 2, sleep_quality=3))
        if day.weekday() == 6:
            session.add(Note(date=day, text="week done", rpe=5))
            continue
        n += 1
        hard = day.weekday() == 5
        session.add(Activity(source="concept2", external_id=f"c{n}", type="rower", start=at(day, 7), duration=2400.0 if hard else 3600.0,
                             distance=10000.0, avg_hr=172 if hard else 135, workout_type="JustRow"))
    session.commit()
    run_matching(session)


def snapshot(session) -> dict:
    rows = session.exec(select(DailyScore).order_by(DailyScore.date)).all()
    out = {}
    for r in rows:
        strain = json.loads(r.strain_json)
        out[r.date] = (round(strain.get("value") or 0, 9), round(strain.get("trimp_like") or 0, 9),
                       json.loads(r.load_json).get("value"), json.loads(r.recovery_json).get("value"), json.loads(r.illness_json).get("level"))
    return out


def test_a_write_recomputes_from_its_own_day_and_matches_a_full_recompute(session):
    seed_weeks(session)
    scoring.recompute_scores(session, full=True)
    # Change one check-in and one RPE two weeks back, recompute only from there...
    day = START + timedelta(days=20)
    row = session.get(CheckIn, tenant.pk(day))
    row.soreness = 5
    session.add(Note(date=day + timedelta(days=1), text="felt rough", rpe=9))
    session.commit()
    count = scoring.recompute_scores(session)  # the session tracked the touched days
    incremental = snapshot(session)
    assert count <= (localtime.today(session) - day).days + 1  # it did not redo the first three weeks
    # ...and it equals redoing everything.
    scoring.recompute_scores(session, full=True)
    assert snapshot(session) == incremental


def test_a_week_of_rows_lifts_and_rest_gives_sensible_ordered_strain(session):
    seed_weeks(session, weeks=1)
    scoring.recompute_scores(session, full=True)
    by_day = {r.date: json.loads(r.strain_json) for r in session.exec(select(DailyScore)).all()}
    saturday = next(d for d in by_day if d.weekday() == 5 and d < START + timedelta(days=7))
    easy = next(d for d in by_day if d.weekday() == 1 and d < START + timedelta(days=7))
    sunday = next(d for d in by_day if d.weekday() == 6 and d < START + timedelta(days=7))
    assert by_day[saturday]["value"] > by_day[easy]["value"] > by_day[sunday]["value"] > 0
    for d in (saturday, easy, sunday):
        s = by_day[d]
        assert s["value"] == pytest.approx(2.54 * math.log1p(s["load"]))  # one curve over one sum, every day
        assert s["muscular"]["load"] == 0.0  # no lifting logged: rows never count again as "muscular"


def test_an_unmerged_watch_workout_overlapping_the_erg_result_counts_once(session):
    localtime.set_preferences(session, home="Europe/London", follow=False)
    update_settings(session, {"max_hr": 190})
    day = START
    session.add(DailyWellness(date=day, resting_hr=50))
    session.add(Activity(source="concept2", external_id="c1", type="rower", start=at(day, 7), duration=3600.0, avg_hr=140, sport_family="rowing"))
    # Whoop's auto-detected version started 4 minutes late and ran 25 % short — outside the matcher's 180 s / 0.8 ratio rules.
    session.add(Activity(source="whoop", external_id="w1", type="rowing", start=at(day, 7) + timedelta(minutes=4), duration=2700.0, avg_hr=138, sport_family="rowing"))
    session.commit()
    run_matching(session)
    strain = scoring.day_strain(session, day, get_settings(session))
    counted = [c for c in strain["components"] if c.get("load") is not None]
    assert len(strain["components"]) == 2 and len(counted) == 1
    assert any(c.get("duplicate_of") for c in strain["components"])
    assert strain["load"] == pytest.approx(counted[0]["load"])


def test_two_genuinely_separate_rows_on_one_day_both_count(session):
    localtime.set_preferences(session, home="Europe/London", follow=False)
    update_settings(session, {"max_hr": 190})
    day = START
    session.add(DailyWellness(date=day, resting_hr=50))
    session.add(Activity(source="concept2", external_id="am", type="rower", start=at(day, 7), duration=3600.0, avg_hr=140))
    session.add(Activity(source="concept2", external_id="pm", type="rower", start=at(day, 17), duration=3600.0, avg_hr=140))
    session.commit()
    run_matching(session)
    strain = scoring.day_strain(session, day, get_settings(session))
    loads = [c["load"] for c in strain["components"]]
    assert len(loads) == 2 and strain["load"] == pytest.approx(sum(loads))
    assert [c["share"] for c in strain["components"]] == [pytest.approx(0.5), pytest.approx(0.5)]


def test_recovery_reads_yesterdays_training_strain_not_its_walking(session):
    localtime.set_preferences(session, home="Europe/London", follow=False)
    for i in range(10):
        session.add(DailyWellness(date=START + timedelta(days=i), resting_hr=50, hrv_rmssd=60, sleep_seconds=8 * 3600, steps=15000))
    session.commit()
    scoring.recompute_scores(session, full=True)
    row = session.get(DailyScore, tenant.pk(START + timedelta(days=9)))
    recovery = json.loads(row.recovery_json)
    prior = next(c for c in recovery["components"] if c["metric"] == "prior_strain")
    assert prior["value"] == pytest.approx(100.0)  # 15k steps yesterday but no training: no recovery penalty
    assert json.loads(row.strain_json)["value"] > 8  # while the day's headline strain does include the walking
