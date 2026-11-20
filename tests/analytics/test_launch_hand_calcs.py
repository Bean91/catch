"""Session 31 launch audit, Part B: formulas checked against hand calculations written out here, independently of the code's
own derivations, plus the missing-data-is-not-zero regressions (docs/launch-audit.md L-13, L-16)."""

import math

import pytest

from catch.analytics.cycling_load import cycling_tss, estimate_ftp_watts
from catch.analytics.erg_math import pace_from_watts, watts_from_pace
from catch.analytics.load import ewma
from catch.analytics.predict import predict_2k
from catch.analytics.recovery import recovery_score
from catch.analytics.strain import banister_trimp, daily_activity_strain
from catch.analytics.strength import epley_e1rm


# -- Concept2: watts = 2.80 / (pace per metre)^3, pace in s/500 m -> s/m = pace/500
@pytest.mark.parametrize(
    "pace_s, watts",
    [
        (100.0, 2.80 / 0.2**3),  # 1:40.0 -> 0.2 s/m -> 2.80/0.008 = 350.0 W
        (120.0, 2.80 / 0.24**3),  # 2:00.0 -> 0.24 s/m -> 2.80/0.013824 = 202.546 W
        (105.0, 2.80 / 0.21**3),  # 1:45.0 -> 0.21 s/m -> 2.80/0.009261 = 302.343 W
    ],
)
def test_concept2_watts_by_hand(pace_s, watts):
    assert watts_from_pace(pace_s) == pytest.approx(watts, rel=1e-9)
    assert pace_from_watts(watts) == pytest.approx(pace_s, rel=1e-9)


def test_concept2_round_numbers():
    assert watts_from_pace(100.0) == pytest.approx(350.0)
    assert pace_from_watts(200.0) == pytest.approx(500 * (2.80 / 200.0) ** (1 / 3))  # = 120.507 s


# -- Paul's law as implemented: 2k pace = pace - 5 * log2(d / 2000)
def test_paul_law_extrapolations_by_hand():
    # 6k @ 1:50.0: log2(3) = 1.58496 -> 110 - 7.9248 = 102.075
    out = predict_2k([{"distance_m": 6000, "pace_s_per_500": 110.0}])
    assert out["components"][0]["predicted_2k_pace_s"] == pytest.approx(110 - 5 * math.log2(3))
    assert out["components"][0]["predicted_2k_pace_s"] == pytest.approx(102.0752, abs=1e-3)
    # 1k @ 1:30.0: log2(0.5) = -1 -> 90 + 5 = 95.0
    assert predict_2k([{"distance_m": 1000, "pace_s_per_500": 90.0}])["components"][0]["predicted_2k_pace_s"] == pytest.approx(95.0)
    # A real 2k at 1:40.0 predicts itself.
    assert predict_2k([{"distance_m": 2000, "pace_s_per_500": 100.0}])["components"][0]["predicted_2k_pace_s"] == pytest.approx(100.0)


# -- Banister TRIMP = minutes * HRr * 0.64 * e^(1.92 * HRr)
def test_banister_trimp_by_hand():
    # 60 min, rest 50, max 190, avg 120 -> HRr = 70/140 = 0.5 -> 60*0.5*0.64*e^0.96 = 19.2*2.611696 = 50.1446
    assert banister_trimp(60, 120, 50, 190) == pytest.approx(19.2 * math.exp(0.96))
    assert banister_trimp(60, 120, 50, 190) == pytest.approx(50.1446, abs=1e-3)
    assert banister_trimp(60, 120, None, 190) is None  # missing input -> no number, not 0


# -- EWMA, lambda = 2/(N+1)
def test_ewma_by_hand():
    # N=7 -> lambda 0.25; series [0, 100]: 0.25*100 + 0.75*0 = 25
    assert ewma([0, 100], 7) == pytest.approx(25.0)
    # [0, 100, 100]: 0.25*100 + 0.75*25 = 43.75
    assert ewma([0, 100, 100], 7) == pytest.approx(43.75)
    assert ewma([50] * 30, 28) == pytest.approx(50.0)


# -- Cycling TSS = 100 * hours * (P/FTP)^2; FTP = 0.95 * best 20 min
def test_cycling_tss_by_hand():
    assert cycling_tss(3600, 200, 250) == pytest.approx(100 * 1 * 0.8**2)  # 64.0
    assert cycling_tss(5400, 250, 250) == pytest.approx(150.0)
    assert estimate_ftp_watts(300) == pytest.approx(285.0)
    assert cycling_tss(3600, None, 250) is None


# -- Epley e1RM = w * (1 + r/30), reps capped at 10
def test_epley_by_hand():
    assert epley_e1rm(100, 5) == pytest.approx(100 * (1 + 5 / 30))  # 116.667
    assert epley_e1rm(100, 10) == pytest.approx(133.333, abs=1e-3)
    assert epley_e1rm(100, 20) == pytest.approx(133.333, abs=1e-3)  # capped (L-17: documented limitation)


# -- Recovery: HRV component = 50 + 25 * z, z = (today - mean(last 7)) / pstdev(last 60)
def test_recovery_hrv_component_by_hand():
    hist = [4.0, 4.2, 4.0, 4.2, 4.0, 4.2, 4.0]
    mean7 = sum(hist) / 7  # 4.085714
    var = sum((x - mean7) ** 2 for x in hist) / 7
    z = (4.2 - mean7) / math.sqrt(var)  # 1.1547
    out = recovery_score(today_ln_hrv=4.2, hrv_history_ln=hist)
    assert out["value"] == pytest.approx(50 + 25 * z)
    assert out["value"] == pytest.approx(78.87, abs=0.01)


# -- Missing data is never a zero (L-16, L-13)
def test_recovery_has_no_score_from_prior_strain_alone():
    out = recovery_score(hrv_history_ln=[4.0] * 7, prior_day_strain=10.5)
    assert out["value"] is None and out["band"] == "insufficient_data"
    out = recovery_score(hrv_history_ln=[4.0] * 7, prior_day_strain=10.5, today_checkin_score=80)
    assert out["value"] is None


def test_recovery_still_scores_from_any_one_physiological_input():
    out = recovery_score(hrv_history_ln=[4.0] * 7, today_sleep_seconds=8 * 3600, prior_day_strain=21)
    # sleep 100 (w 0.2) + strain 0 (w 0.15) -> 20/0.35 = 57.14
    assert out["value"] == pytest.approx(20 / 0.35)


def test_activity_strain_does_not_average_a_missing_kcal_in_as_zero():
    from catch.analytics.defaults import DEFAULT_SETTINGS

    w, cap = DEFAULT_SETTINGS["daily_activity_strain_weight"], DEFAULT_SETTINGS["daily_activity_strain_cap"]
    # 6000 steps: log1p(6000/2000) = log1p(3) = 1.3863 on its own; the old code halved it to 0.6931 by averaging in a 0 kcal term.
    assert daily_activity_strain(6000, None)["value"] == pytest.approx(min(cap, w * math.log1p(3)))
    # A real 0 kcal is still a real 0 and is averaged in.
    assert daily_activity_strain(6000, 0)["value"] == pytest.approx(min(cap, w * math.log1p(3) / 2))
    assert daily_activity_strain(None, None)["value"] == 0.0
