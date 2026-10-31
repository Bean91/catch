from __future__ import annotations

import pytest

from catch.analytics.recovery import recovery_score

HRV_HISTORY = [4.0, 4.1, 3.9, 4.0, 4.2, 3.8, 4.0]  # mean 4.0, pstdev ~0.1195
RHR_HISTORY = [50.0, 52.0, 48.0, 50.0, 54.0, 46.0, 50.0]  # mean 50, pstdev ~2.39


def test_calibrating_before_seven_nights_of_hrv():
    result = recovery_score(hrv_history_ln=[4.0] * 6, today_ln_hrv=4.0)
    assert result["value"] is None
    assert result["band"] == "calibrating"


def test_green_band_when_everything_trends_good():
    result = recovery_score(
        today_ln_hrv=4.2,
        hrv_history_ln=HRV_HISTORY,
        today_resting_hr=46.0,
        rhr_history=RHR_HISTORY,
        today_sleep_seconds=7 * 3600,
        prior_day_strain=10.5,
    )
    assert result["value"] == pytest.approx(84.7, abs=0.5)
    assert result["band"] == "green"


def test_yellow_band_at_neutral_values():
    result = recovery_score(
        today_ln_hrv=4.0,
        hrv_history_ln=HRV_HISTORY,
        today_resting_hr=50.0,
        rhr_history=RHR_HISTORY,
        today_sleep_seconds=6 * 3600,
        prior_day_strain=12.0,
    )
    assert result["band"] == "yellow"


def test_red_band_when_everything_trends_bad():
    result = recovery_score(
        today_ln_hrv=3.8,
        hrv_history_ln=HRV_HISTORY,
        today_resting_hr=54.0,
        rhr_history=RHR_HISTORY,
        today_sleep_seconds=4 * 3600,
        prior_day_strain=18.0,
    )
    assert result["band"] == "red"


def test_insufficient_data_when_no_todays_values_given():
    result = recovery_score(hrv_history_ln=HRV_HISTORY)
    assert result["value"] is None
    assert result["band"] == "insufficient_data"


def test_zero_spread_history_drops_that_component_rather_than_crashing():
    result = recovery_score(
        today_ln_hrv=4.5,
        hrv_history_ln=[4.0] * 7,  # no variance -> hrv component must be skipped, not div/0
        today_sleep_seconds=7 * 3600,
        prior_day_strain=5.0,
    )
    assert result["value"] is not None
    assert all(c["value"] is None for c in result["components"] if c["metric"] == "hrv")
