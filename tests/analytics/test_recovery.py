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


# --- Session 15 Part A.2: subjective check-in -------------------------------------------

_BASE_KWARGS = dict(
    today_ln_hrv=4.2,
    hrv_history_ln=HRV_HISTORY,
    today_resting_hr=46.0,
    rhr_history=RHR_HISTORY,
    today_sleep_seconds=7 * 3600,
    prior_day_strain=10.5,
)


def test_recovery_is_identical_with_no_checkin_logged():
    """A day with no check-in must score exactly as it would have before this feature
    existed — the additive weight must never implicitly renormalize the other four."""
    without_the_kwarg_at_all = recovery_score(**_BASE_KWARGS)
    with_explicit_none = recovery_score(**_BASE_KWARGS, today_checkin_score=None)
    assert without_the_kwarg_at_all["value"] == with_explicit_none["value"]
    assert without_the_kwarg_at_all["band"] == with_explicit_none["band"]
    assert not any(c["metric"] == "checkin" for c in with_explicit_none["components"])


def test_a_bad_checkin_pulls_the_blended_value_down():
    without_checkin = recovery_score(**_BASE_KWARGS)
    with_bad_checkin = recovery_score(**_BASE_KWARGS, today_checkin_score=0.0)
    assert with_bad_checkin["value"] < without_checkin["value"]
    checkin_component = next(c for c in with_bad_checkin["components"] if c["metric"] == "checkin")
    assert checkin_component["value"] == pytest.approx(0.0)


def test_a_great_checkin_pulls_the_blended_value_up():
    without_checkin = recovery_score(**_BASE_KWARGS)
    with_great_checkin = recovery_score(**_BASE_KWARGS, today_checkin_score=100.0)
    assert with_great_checkin["value"] > without_checkin["value"]
