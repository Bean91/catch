from __future__ import annotations

from catch.analytics.wake_time import average_wake_time_minutes


def test_no_samples_returns_none():
    assert average_wake_time_minutes([]) is None


def test_averages_and_rounds():
    # 6:00, 6:30, 7:00 -> mean 6:30, rounds exactly
    assert average_wake_time_minutes([360, 390, 420]) == 390


def test_rounds_to_nearest_minute():
    assert average_wake_time_minutes([400, 401]) == round(400.5)
