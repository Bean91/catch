"""Session 32: the 2k estimate (catch/analytics/predict.py). Hand-computed with Paul's law, 2k pace = pace - 5 * log2(d / 2000)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from catch.analytics.erg_math import pace_from_watts, watts_from_pace
from catch.analytics.predict import effort_class, implied_2k_time, predict_2k

TODAY = date(2026, 11, 20)


def pt(distance, seconds, days_ago=7, effort="declared", label=None):
    return {"distance_m": distance, "duration_s": seconds, "date": TODAY - timedelta(days=days_ago), "effort": effort, "label": label}


# -- Paul's law and unit conversions ------------------------------------------------------------------------------------------


def test_implied_2k_by_hand_for_several_distances():
    # 6k in 22:00 (1:50.0/500 m): 110 - 5*log2(3) = 102.075 s/500 -> 408.30 s.
    assert implied_2k_time(6000, 1320.0) == pytest.approx(4 * (110 - 5 * math.log2(3)))
    # 5k in 18:00 (1:48.0): 108 - 5*log2(2.5) = 101.390 -> 405.56 s.
    assert implied_2k_time(5000, 1080.0) == pytest.approx(4 * (108 - 5 * math.log2(2.5)))
    # 1k in 3:10 (1:35.0): 95 + 5 = 100.0 -> 400.0 s.
    assert implied_2k_time(1000, 190.0) == pytest.approx(400.0)
    # 500 m in 1:30 (1:30.0): 90 + 10 = 100.0 -> 400.0 s.
    assert implied_2k_time(500, 90.0) == pytest.approx(400.0)
    # A 2k predicts itself.
    assert implied_2k_time(2000, 412.3) == pytest.approx(412.3)
    # 30 minutes for 7,800 m (pace 115.38): 115.38 - 5*log2(3.9) -> 4 x 105.57.
    assert implied_2k_time(7800, 1800.0) == pytest.approx(4 * (1800 / 7800 * 500 - 5 * math.log2(3.9)))


def test_pace_watts_round_trip_uses_seconds_per_metre_cubed():
    # Concept2: watts = 2.80 / (pace / 500)^3, pace in s/500 m. 1:40.0 -> 350 W.
    assert watts_from_pace(100.0) == pytest.approx(350.0)
    assert pace_from_watts(watts_from_pace(107.3)) == pytest.approx(107.3)


# -- Known results and performance levels -------------------------------------------------------------------------------------


@pytest.mark.parametrize("two_k_s", [345.0, 390.0, 420.0, 480.0, 540.0])  # elite man, club, ~7:00, novice, beginner
def test_a_recent_measured_2k_alone_is_estimated_as_itself(two_k_s):
    out = predict_2k([pt(2000, two_k_s)], TODAY)
    assert out["predicted_time_s"] == pytest.approx(two_k_s)
    assert out["value"] == pytest.approx(two_k_s / 4)
    lo, hi = out["range_s"]
    assert lo < two_k_s < hi and hi - lo == pytest.approx(2 * 2.0)  # the day-to-day floor only: no extrapolation, no spread
    assert out["confidence"] == "moderate"  # one effort is never "high"
    assert "not a measured result" in out["explanation"]


def test_two_recent_strong_efforts_near_2k_give_high_confidence():
    out = predict_2k([pt(2000, 400.0, 10), pt(1000, 190.0, 20)], TODAY)
    assert out["confidence"] == "high"
    assert 399.0 < out["predicted_time_s"] < 401.0


def test_a_consistent_athlete_across_distances_is_estimated_consistently():
    # Built from one 2k pace of 100.0 s/500 m: every effort implies exactly 400.0 s.
    efforts = [pt(d, d / 500 * (100.0 + 5 * math.log2(d / 2000)), 14) for d in (1000, 5000, 6000, 10000)]
    out = predict_2k(efforts, TODAY)
    assert out["predicted_time_s"] == pytest.approx(400.0)
    assert out["excluded_count"] == 0


# -- Effort selection ---------------------------------------------------------------------------------------------------------


def test_effort_classes_from_heart_rate():
    assert effort_class(declared=True, avg_hr=None, max_hr=None) == "declared"
    assert effort_class(declared=False, avg_hr=172, max_hr=195) == "hr_verified"  # 88 % of max
    assert effort_class(declared=False, avg_hr=140, max_hr=195) is None  # steady: never evidence
    assert effort_class(declared=False, avg_hr=None, max_hr=195) == "effort_unknown"
    assert effort_class(declared=False, avg_hr=170, max_hr=None) == "effort_unknown"


def test_submaximal_rows_cannot_drag_the_estimate_slower():
    # A 6:40 2k test, plus slow 10k rows that imply ~7:40 (no HR, so they could have been steady).
    efforts = [pt(2000, 400.0, 20)] + [pt(10000, 10000 / 500 * 125.0, d, effort="effort_unknown") for d in (2, 5, 9)]
    out = predict_2k(efforts, TODAY)
    assert out["predicted_time_s"] == pytest.approx(400.0)
    assert out["excluded_count"] == 3


def test_a_flattering_500m_sprint_never_discards_a_measured_2k():
    # A 500 m test at 1:22.0 implies 4 x (82 + 10) = 368 s (6:08); the real 2k is 6:30 (390 s), 6 % slower. The 2k must stay and win.
    out = predict_2k([pt(500, 82.0, 5), pt(2000, 390.0, 12)], TODAY)
    assert out["excluded_count"] == 0
    assert out["predicted_time_s"] == pytest.approx(390.0)


def test_distances_outside_500m_to_10k_never_count():
    out = predict_2k([pt(21097, 21097 / 500 * 110.0), pt(250, 40.0)], TODAY)
    assert out["confidence"] == "insufficient_data" and out["predicted_time_s"] is None


def test_recent_evidence_beats_an_old_faster_result():
    # A 6:20 test from 300 days ago and a recent 5k that implies ~6:55: the athlete is slower now, and the estimate says so.
    five_k = 5000 / 500 * (103.75 + 5 * math.log2(2.5))  # implies 415.0 s
    out = predict_2k([pt(2000, 380.0, 300), pt(5000, five_k, 10)], TODAY)
    assert out["predicted_time_s"] == pytest.approx(415.0)
    assert out["stale"] is False


# -- Stale, inconsistent and insufficient data --------------------------------------------------------------------------------


def test_only_old_strong_efforts_give_a_low_confidence_wider_range_that_says_why():
    fresh = predict_2k([pt(2000, 400.0, 10)], TODAY)
    old = predict_2k([pt(2000, 400.0, 200)], TODAY)
    assert old["stale"] is True and old["confidence"] == "low"
    assert old["range_s"][1] - old["range_s"][0] > fresh["range_s"][1] - fresh["range_s"][0]
    assert "4 months" in old["explanation"]


def test_nothing_in_the_last_year_is_insufficient():
    out = predict_2k([pt(2000, 400.0, 400)], TODAY)
    assert out["confidence"] == "insufficient_data" and out["value"] is None and out["range_s"] is None


def test_no_evidence_at_all_is_insufficient():
    out = predict_2k([], TODAY)
    assert out["band"] == "insufficient_data" and out["components"] == [] and out["predicted_time_s"] is None


def test_only_unknown_effort_rows_are_low_confidence_and_flagged_as_possibly_too_slow():
    out = predict_2k([pt(5000, 5000 / 500 * 110.0, 3, effort="effort_unknown")], TODAY)
    assert out["confidence"] == "low"
    assert "may be too slow" in out["explanation"]


def test_old_unknown_effort_rows_alone_are_insufficient():
    out = predict_2k([pt(5000, 1100.0, 200, effort="effort_unknown")], TODAY)
    assert out["confidence"] == "insufficient_data"


def test_inconsistent_efforts_widen_the_range():
    tight = predict_2k([pt(2000, 400.0, 5), pt(2000, 401.0, 12)], TODAY)
    loose = predict_2k([pt(2000, 400.0, 5), pt(2000, 412.0, 12)], TODAY)
    assert (loose["range_s"][1] - loose["range_s"][0]) > (tight["range_s"][1] - tight["range_s"][0])


def test_incomplete_rows_are_skipped_not_crashed_on():
    rows = [{"distance_m": None, "duration_s": 400.0, "date": TODAY, "effort": "declared"}, {"distance_m": 2000, "duration_s": 0, "date": TODAY, "effort": "declared"},
            {"distance_m": 2000, "duration_s": 400.0, "date": None, "effort": "declared"}, {"distance_m": 2000, "duration_s": 400.0, "date": TODAY, "effort": "steady"},
            {"distance_m": 2000, "duration_s": 400.0, "date": TODAY + timedelta(days=3), "effort": "declared"}]
    assert predict_2k(rows, TODAY)["confidence"] == "insufficient_data"


def test_extrapolating_from_far_distances_is_less_certain_than_a_2k():
    near = predict_2k([pt(2000, 400.0, 5)], TODAY)
    far = predict_2k([pt(10000, 10000 / 500 * (100 + 5 * math.log2(5)), 5)], TODAY)
    assert far["predicted_time_s"] == pytest.approx(400.0)
    assert (far["range_s"][1] - far["range_s"][0]) > (near["range_s"][1] - near["range_s"][0])
    assert far["confidence"] == "low" and "well away from 2,000 m" in far["explanation"]


def test_the_legacy_pace_keys_agree_with_the_seconds():
    out = predict_2k([pt(2000, 400.0, 5), pt(6000, 1320.0, 9)], TODAY)
    assert out["value"] == pytest.approx(out["predicted_time_s"] / 4)
    assert out["range"][0] == pytest.approx(out["range_s"][0] / 4) and out["range"][1] == pytest.approx(out["range_s"][1] / 4)
