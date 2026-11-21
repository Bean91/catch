"""Session 33: which resting heart rate a day's zones use (catch/analytics/hr_basis.py)."""

from __future__ import annotations

from datetime import date, timedelta

from catch.analytics.hr_basis import zone_resting_hr

DAY = date(2026, 11, 20)


def _days(values, end=DAY):
    return [(end - timedelta(days=len(values) - i), v) for i, v in enumerate(values)]


def test_median_of_the_14_days_before():
    out = zone_resting_hr(_days([50, 52, 48, 51, 49, 50, 53]), DAY)
    assert out["source"] == "measured" and out["resting_hr"] == 50 and out["readings"] == 7


def test_one_anomalous_night_does_not_move_it():
    calm = zone_resting_hr(_days([50] * 13 + [50]), DAY)["resting_hr"]
    sick = zone_resting_hr(_days([50] * 13 + [72]), DAY)["resting_hr"]
    assert calm == sick == 50


def test_the_days_own_reading_is_not_used():
    readings = _days([50, 50, 50, 50]) + [(DAY, 90)]
    assert zone_resting_hr(readings, DAY)["resting_hr"] == 50


def test_needs_four_readings_then_falls_back_to_a_stale_median():
    few = _days([50, 51, 52])
    assert zone_resting_hr(few, DAY)["source"] == "none"
    old = [(DAY - timedelta(days=40 + i), 55.0) for i in range(5)]
    out = zone_resting_hr(old, DAY)
    assert out["source"] == "measured_stale" and out["resting_hr"] == 55


def test_nothing_within_60_days_is_none():
    ancient = [(DAY - timedelta(days=90 + i), 55.0) for i in range(10)]
    assert zone_resting_hr(ancient, DAY) == {"resting_hr": None, "source": "none", "window": None, "readings": 0}


def test_the_athletes_own_value_wins():
    out = zone_resting_hr(_days([50] * 10), DAY, override=44)
    assert out == {"resting_hr": 44.0, "source": "setting", "window": None, "readings": 0}


def test_implausible_readings_are_ignored():
    out = zone_resting_hr(_days([50, 50, 50, 50, 0, 250, None]), DAY)
    assert out["resting_hr"] == 50 and out["readings"] == 4
