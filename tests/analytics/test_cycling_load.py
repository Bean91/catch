from __future__ import annotations

import pytest

from catch.analytics.cycling_load import best_rolling_power, cycling_tss, estimate_ftp_watts


def test_estimate_ftp_is_95_percent_of_best_20min():
    assert estimate_ftp_watts(200.0) == 190.0
    assert estimate_ftp_watts(None) is None
    assert estimate_ftp_watts(0) is None


def test_best_rolling_power_finds_the_strongest_20min_window():
    # 10 min easy (100W), 20 min hard (250W), 10 min easy again — the best 20-min window
    # must land exactly on the hard block, not blend in any of the easy minutes.
    samples = [100.0] * 600 + [250.0] * 1200 + [100.0] * 600
    assert best_rolling_power(samples, window_s=1200) == 250.0


def test_best_rolling_power_none_when_recording_shorter_than_the_window():
    assert best_rolling_power([200.0] * 1000, window_s=1200) is None


def test_best_rolling_power_skips_a_window_with_too_many_gaps():
    # A 20-min window that's half missing shouldn't produce a falsely-high average from the
    # few real samples it does have.
    samples = ([300.0] * 100 + [None] * 1100) + [150.0] * 1200
    result = best_rolling_power(samples, window_s=1200)
    assert result == 150.0


def test_cycling_tss_matches_the_standard_formula_at_if_1():
    # One hour exactly at FTP (IF=1.0) is defined as 100 TSS.
    assert cycling_tss(3600.0, avg_power=200.0, ftp_watts=200.0) == 100.0


def test_cycling_tss_scales_with_intensity_factor_squared():
    hour_at_ftp = cycling_tss(3600.0, 200.0, 200.0)
    half_hour_at_double_ftp = cycling_tss(1800.0, 400.0, 200.0)
    # IF=2.0 for half the time: 100 * 0.5 * 2.0^2 = 200 — harder, shorter, still scores high.
    assert half_hour_at_double_ftp == pytest.approx(200.0)
    assert half_hour_at_double_ftp > hour_at_ftp


def test_cycling_tss_none_without_ftp():
    assert cycling_tss(3600.0, 200.0, None) is None
    assert cycling_tss(3600.0, None, 200.0) is None
    assert cycling_tss(None, 200.0, 200.0) is None
