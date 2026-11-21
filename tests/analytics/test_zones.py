"""Training zones (docs/analytics.md §3). Session 33: heart-rate-reserve (Karvonen) zones by default, % of max HR as a choice and
as the stated fallback, no zones without a max HR."""

from __future__ import annotations

import pytest

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.analytics.zones import (
    FALLBACK_BAD_RESERVE,
    FALLBACK_NO_RHR,
    NO_MAX_HR,
    basis_from_dict,
    hr_basis,
    hr_zone_bounds,
    training_zones,
    zone_for_hr,
    zone_for_power,
)

HRR_PCT = DEFAULT_SETTINGS["zones"]["hrr_pct"]


def _settings(**kw):
    return {**DEFAULT_SETTINGS, **kw}


@pytest.mark.parametrize(("max_hr", "rest"), [(190, 50), (190, 40), (200, 60), (175, 48), (205, 38)])
def test_karvonen_bounds_for_different_resting_and_max_heart_rates(max_hr, rest):
    basis = hr_basis(_settings(max_hr=max_hr), rest, rhr_source="measured")
    assert basis.method == "hrr"
    bounds = hr_zone_bounds(basis)
    for zone, pct in HRR_PCT.items():
        assert bounds[zone] == pytest.approx(rest + (max_hr - rest) * pct / 100)


def test_a_lower_resting_heart_rate_widens_the_reserve_and_lowers_easy_zones():
    fit = hr_zone_bounds(hr_basis(_settings(max_hr=190), 42))
    less_fit = hr_zone_bounds(hr_basis(_settings(max_hr=190), 62))
    assert fit["UT2"] < less_fit["UT2"]
    assert fit["AN"] < less_fit["AN"]  # 42 + 148*.95 = 182.6 vs 62 + 128*.95 = 183.6


def test_gb_rowing_defaults_at_190_max_and_50_resting():
    bounds = hr_zone_bounds(hr_basis(_settings(max_hr=190), 50))
    assert {z: round(b, 1) for z, b in bounds.items()} == {"UT2": 132.6, "UT1": 143.8, "AT": 155.0, "TR": 169.0, "AN": 183.0}


def test_zone_boundary_transitions_are_inclusive_of_the_higher_zone():
    basis = hr_basis(_settings(max_hr=190), 50)
    bounds = hr_zone_bounds(basis)
    assert zone_for_hr(bounds["UT1"], basis) == "UT1"
    assert zone_for_hr(bounds["UT1"] - 0.01, basis) == "UT2"
    assert zone_for_hr(bounds["AN"], basis) == "AN"
    assert zone_for_hr(60, basis) == "UT2"  # below UT2's bound still reads UT2, as before
    assert zone_for_hr(None, basis) is None


def test_missing_resting_heart_rate_falls_back_to_percent_of_max_and_says_so():
    basis = hr_basis(_settings(max_hr=190), None)
    assert basis.method == "max_pct" and basis.requested_method == "hrr" and basis.reason == FALLBACK_NO_RHR
    assert hr_zone_bounds(basis)["UT2"] == pytest.approx(190 * 0.60)


def test_missing_max_heart_rate_gives_no_zones_and_never_invents_one():
    basis = hr_basis(_settings(max_hr=None), 50)
    assert basis.method == "none" and basis.reason == NO_MAX_HR
    assert hr_zone_bounds(basis) == {}
    assert zone_for_hr(150, basis) is None
    zones = {z["zone"]: z for z in training_zones(basis)["zones"]}
    assert zones["UT1"]["hr_lo"] is None


@pytest.mark.parametrize("bad", [10, 150, -5])
def test_implausible_resting_heart_rates_are_ignored(bad):
    basis = hr_basis(_settings(max_hr=190), bad)
    assert basis.method == "max_pct" and basis.resting_hr is None


def test_a_reserve_too_small_to_divide_falls_back():
    basis = hr_basis(_settings(max_hr=120), 95)
    assert basis.method == "max_pct" and basis.reason == FALLBACK_BAD_RESERVE


def test_percent_of_max_is_still_a_choice():
    basis = hr_basis(_settings(max_hr=190, hr_zone_method="max_pct"), 50)
    assert basis.method == "max_pct" and basis.reason is None
    assert zone_for_hr(150, basis) == "UT1"  # 78.9 % of max


def test_training_zones_table_carries_bpm_and_its_basis():
    result = training_zones(hr_basis(_settings(max_hr=190), 50))
    zones = {z["zone"]: z for z in result["zones"]}
    assert zones["UT2"]["hr_lo"] == pytest.approx(132.6)
    assert zones["UT2"]["hr_hi"] == pytest.approx(143.8)
    assert zones["UT2"]["hr_pct_lo"] == 59
    assert zones["AN"]["hr_hi"] is None
    assert result["hr_basis"]["method"] == "hrr" and result["hr_basis"]["resting_hr"] == 50
    assert "defaults" in result["note"].lower()


def test_a_stored_basis_round_trips():
    basis = hr_basis(_settings(max_hr=190), 51.5, rhr_source="measured", rhr_window=["2026-11-01", "2026-11-14"], rhr_readings=12)
    again = basis_from_dict(basis.as_dict())
    assert again == basis


def test_zone_for_power():
    watts_2k = 300.0
    assert zone_for_power(270.0, watts_2k) == "TR"
    assert zone_for_power(None, watts_2k) is None
