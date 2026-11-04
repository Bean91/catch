from __future__ import annotations

import pytest

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.analytics.strain import banister_trimp, daily_activity_strain, session_strain, srpe_load, time_in_zone


def test_banister_trimp_hand_check():
    # 60 min at HRr=0.5 (avg 120, resting 50, max 190), b=1.92 -> ~50.14 AU.
    trimp = banister_trimp(duration_minutes=60, avg_hr=120, resting_hr=50, max_hr=190, trimp_exponent=1.92)
    assert trimp == pytest.approx(50.14, abs=0.05)


def test_banister_trimp_missing_inputs_returns_none():
    assert banister_trimp(60, None, 50, 190) is None
    assert banister_trimp(None, 120, 50, 190) is None
    assert banister_trimp(60, 120, 50, 50) is None  # max_hr <= resting_hr


def test_srpe_load_calibrated_against_trimp_anchor():
    # Scaled so a 60-min RPE-5 session (sRPE=300 AU) ~ matches the HRr=0.5 TRIMP anchor (~50).
    assert srpe_load(rpe=5, duration_minutes=60, scale=50 / 300) == pytest.approx(50.0)
    assert srpe_load(rpe=None, duration_minutes=60, scale=50 / 300) is None


def test_session_strain_prefers_hr_over_rpe():
    result = session_strain(duration_minutes=90, avg_hr=150, resting_hr=50, max_hr=190, rpe=8)
    assert result["components"][0]["method"] == "trimp"
    assert result["band"] == "moderate"
    assert 10 <= result["value"] < 14


def test_session_strain_falls_back_to_rpe_without_hr():
    result = session_strain(duration_minutes=60, avg_hr=None, resting_hr=None, max_hr=190, rpe=5)
    assert result["components"][0]["method"] == "srpe"
    assert result["value"] is not None


def test_session_strain_insufficient_data():
    result = session_strain(duration_minutes=60, avg_hr=None, resting_hr=None, max_hr=None, rpe=None)
    assert result["value"] is None
    assert result["band"] == "insufficient_data"


def test_time_in_zone_buckets_by_hr_pct_of_max():
    samples = [(60.0, 100.0), (60.0, 150.0), (60.0, 180.0)]
    totals = time_in_zone(samples, max_hr=190)
    # 100/190=52.6% (<60, clamps to UT2), 150/190=78.9% (UT1), 180/190=94.7% (AN).
    assert totals["UT2"] == pytest.approx(60.0)
    assert totals["UT1"] == pytest.approx(60.0)
    assert totals["AN"] == pytest.approx(60.0)
    assert totals["AT"] == 0.0
    assert totals["TR"] == 0.0


def test_time_in_zone_without_max_hr_returns_zeros():
    totals = time_in_zone([(60.0, 150.0)], max_hr=None)
    assert all(v == 0.0 for v in totals.values())


def test_daily_activity_strain_zero_when_no_data():
    result = daily_activity_strain(None, None, DEFAULT_SETTINGS)
    assert result["value"] == 0.0
    assert result["steps"] is None


def test_daily_activity_strain_diminishing_returns():
    low = daily_activity_strain(4000, 150, DEFAULT_SETTINGS)
    high = daily_activity_strain(16000, 700, DEFAULT_SETTINGS)
    # Quadrupling steps/kcal doesn't come close to quadrupling the contribution.
    assert low["value"] > 0
    assert high["value"] < 4 * low["value"]


def test_daily_activity_strain_respects_cap_and_weight():
    settings = {**DEFAULT_SETTINGS, "daily_activity_strain_cap": 1.5, "daily_activity_strain_weight": 1.0}
    result = daily_activity_strain(30000, 1500, settings)
    assert result["value"] == pytest.approx(1.5)

    zero_weight = {**DEFAULT_SETTINGS, "daily_activity_strain_weight": 0.0}
    assert daily_activity_strain(30000, 1500, zero_weight)["value"] == 0.0

    higher_cap = {**DEFAULT_SETTINGS, "daily_activity_strain_cap": 5.0, "daily_activity_strain_weight": 1.0}
    assert daily_activity_strain(30000, 1500, higher_cap)["value"] < 5.0


def test_daily_activity_strain_negative_inputs_clamp_to_zero():
    # A workout's own steps/kcal can exceed the day's Garmin total on a short/odd sync
    # window; never show a negative non-exercise contribution.
    result = daily_activity_strain(-500, -50, DEFAULT_SETTINGS)
    assert result["value"] == 0.0
