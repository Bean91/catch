from __future__ import annotations

import math

import pytest

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.analytics.strain import banister_trimp, daily_activity_trimp, session_strain, srpe_load, time_in_zone


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


def test_daily_activity_trimp_zero_when_no_data():
    result = daily_activity_trimp(None, None, DEFAULT_SETTINGS)
    assert result["load"] == 0.0
    assert result["steps"] is None


def test_daily_activity_trimp_is_walking_minutes_at_easy_heart_rate():
    # 10,000 steps = 100 easy-walking minutes x Banister per-minute TRIMP at 25 % HRR (0.25 x 0.64 x e^0.48 = 0.2586).
    per_min = 0.25 * 0.64 * math.exp(1.92 * 0.25)
    assert daily_activity_trimp(10000, None, DEFAULT_SETTINGS)["load"] == pytest.approx(100 * per_min)
    # Steps win over kcal; kcal is used only without steps (400 kcal / 4 per minute = 100 minutes).
    assert daily_activity_trimp(10000, 9999, DEFAULT_SETTINGS)["basis"] == "steps"
    assert daily_activity_trimp(None, 400, DEFAULT_SETTINGS)["load"] == pytest.approx(100 * per_min)


def test_daily_activity_trimp_is_capped():
    assert daily_activity_trimp(60000, None, DEFAULT_SETTINGS)["load"] == pytest.approx(DEFAULT_SETTINGS["daily_activity_trimp_cap"])


def test_daily_activity_trimp_negative_inputs_clamp_to_zero():
    # A workout's own steps/kcal can exceed the day's wearable total on an odd sync window; never a negative contribution.
    assert daily_activity_trimp(-500, -50, DEFAULT_SETTINGS)["load"] == 0.0
