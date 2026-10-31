from __future__ import annotations

from datetime import date, timedelta

from catch.analytics.body import smooth_weight


def test_empty_readings():
    assert smooth_weight([]) == []


def test_single_day_outlier_does_not_move_smoothed_line():
    start = date(2026, 1, 1)
    readings = [(start + timedelta(days=i), 80.0) for i in range(6)]
    readings.append((start + timedelta(days=6), 95.0))  # one-day spike
    smoothed = dict(smooth_weight(readings))
    # Window for day 6 is days 0-6: six 80.0s + one 95.0 -> median still 80.0.
    assert smoothed[start + timedelta(days=6)] == 80.0


def test_same_day_readings_are_averaged_first():
    day = date(2026, 1, 1)
    smoothed = dict(smooth_weight([(day, 79.0), (day, 81.0)]))
    assert smoothed[day] == 80.0


def test_gradual_trend_tracked_by_median():
    start = date(2026, 1, 1)
    readings = [(start + timedelta(days=i), 80.0 + i) for i in range(10)]
    smoothed = dict(smooth_weight(readings))
    # Window for day 9 is days 3-9 (7 values: 83..89) -> median 86.
    assert smoothed[start + timedelta(days=9)] == 86.0
