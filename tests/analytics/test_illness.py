from __future__ import annotations

import pytest

from catch.analytics.illness import illness_score

# Constant-history baselines (pstdev=0) exercise the SD floors directly — every deviation
# below is computed against `max(0, floor)`, i.e. exactly the floor, so the exact numbers
# in each scenario are easy to hand-check against defaults.py's
# illness_sd_floor_rhr=1.5 / illness_sd_floor_hrv_ln=0.05 / illness_sd_floor_resp=0.5 and
# illness_sd_threshold=1.5.
_N = 20
RHR_BASELINE = [50.0] * _N
HRV_LN_BASELINE = [4.0] * _N
RESP_BASELINE = [14.0] * _N


def _night(**overrides) -> dict:
    base = dict(
        today_resting_hr=50.0,
        resting_hr_history=RHR_BASELINE,
        today_ln_hrv=4.0,
        hrv_history_ln=HRV_LN_BASELINE,
        today_resp=14.0,
        resp_history=RESP_BASELINE,
        prev_deviated_count=0,
        acr=1.0,
    )
    base.update(overrides)
    return base


def test_none_when_nothing_deviates():
    result = illness_score(**_night())
    assert result["level"] == "none"
    assert result["deviated_count"] == 0


def test_insufficient_baseline_history_leaves_a_signal_unavailable_not_deviated():
    result = illness_score(**_night(resting_hr_history=RHR_BASELINE[:5], today_resting_hr=80.0))
    assert result["signals"]["resting_hr"]["z"] is None
    assert result["signals"]["resting_hr"]["deviated"] is False
    assert result["level"] == "none"


def test_a_real_illness_pattern_reaches_likely_only_on_the_second_night():
    # Night 1: RHR/HRV/respiration all deviate together, but nothing has persisted yet.
    night1 = illness_score(**_night(today_resting_hr=53.0, today_ln_hrv=3.9, today_resp=15.0))
    assert night1["deviated_count"] == 3
    assert night1["level"] == "watch"

    # Night 2: the same three signals deviate again -> 2-night persistence -> likely.
    night2 = illness_score(
        **_night(today_resting_hr=53.0, today_ln_hrv=3.9, today_resp=15.0, prev_deviated_count=night1["deviated_count"])
    )
    assert night2["level"] == "likely"
    assert "strain or illness" in night2["explanation"]
    for forbidden in ("sick", "diagnos"):
        assert forbidden not in night2["explanation"].lower()


def test_a_single_bad_night_after_a_late_party_never_reaches_likely():
    # RHR and HRV both deviate (plausible after alcohol/a late night), respiration doesn't,
    # and — the key fact — there was no deviation the night before, so persistence can't be
    # satisfied no matter how many signals this one night trips.
    result = illness_score(**_night(today_resting_hr=53.0, today_ln_hrv=3.9, prev_deviated_count=0))
    assert result["deviated_count"] == 2
    assert result["level"] == "watch"


def test_a_hard_training_block_never_reaches_likely_even_with_persistence():
    # RHR/HRV deviate persistently (a real, expected training response), respiration and
    # check-in don't, and ACR is already high — exactly the pattern a training block
    # produces, which must be capped at "watch", not escalated to "likely".
    result = illness_score(
        today_resting_hr=52.5,
        resting_hr_history=RHR_BASELINE,
        today_ln_hrv=3.92,
        hrv_history_ln=HRV_LN_BASELINE,
        today_resp=14.1,
        resp_history=RESP_BASELINE,
        prev_deviated_count=2,
        acr=1.4,
    )
    assert result["deviated_count"] == 2
    assert result["level"] == "watch"
    assert "high" in result["explanation"].lower()


def test_a_non_training_signal_overrides_the_high_load_discount():
    # Same high-ACR situation, but this time respiration also deviates — a training block
    # doesn't explain a respiration bump, so the discount should not apply and this reaches
    # "likely" (2-night persistence is still required).
    result = illness_score(
        today_resting_hr=52.5,
        resting_hr_history=RHR_BASELINE,
        today_ln_hrv=3.92,
        hrv_history_ln=HRV_LN_BASELINE,
        today_resp=15.0,
        resp_history=RESP_BASELINE,
        prev_deviated_count=3,
        acr=1.4,
    )
    assert result["level"] == "likely"


def test_checkin_signal_needs_its_own_baseline_before_it_counts():
    short_history = [10.0] * 3  # fewer than illness_min_checkin_baseline (5)
    result = illness_score(**_night(today_checkin_badness=90.0, checkin_badness_history=short_history))
    assert result["signals"]["checkin"]["deviated"] is False


def test_wording_never_diagnoses():
    result = illness_score(**_night(today_resting_hr=55.0))
    assert result["level"] == "watch"
    for forbidden in ("sick", "diagnos", "you have", "you are ill"):
        assert forbidden not in result["explanation"].lower()
