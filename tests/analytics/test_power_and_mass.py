"""Session 34: watts from split pace (Concept2's formula, the one implementation) and weight-adjusted power (W/kg^(2/3)).

Worked examples, by hand:
- P = 2.8 / (t/500)^3. 2:00.0 → 2.8 / 0.24^3 = 202.546 W; 1:50.0 → 2.8 / 0.22^3 = 262.96 W; 1:45.0 → 2.8 / 0.21^3 = 302.343 W;
  1:40.0 → 2.8 / 0.2^3 = 350.0 W. (The brief listed 175/227/259/294 W; no single formula gives those, and they contradict its own P.)
- 302.343 W at 80 kg: 80^(2/3) = 18.566 → 16.285 W/kg^(2/3); at 70 kg: 70^(2/3) = 16.985 → 17.801. W/kg at 80 kg = 3.779.
- 176.37 lb × 0.45359237 = 80.000 kg."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from catch.analytics.bodyweight import AFTER_DAYS, BEFORE_DAYS, plausible_body_mass, weight_for_day
from catch.analytics.erg_math import pace_from_watts, w_per_kg, watts_from_pace, weight_adjusted_power
from catch.analytics.piece import (
    aggregate_from_splits,
    piece_avg_watts,
    row_pace_500,
    totals_only_splits,
    validate_splits,
    with_derived_watts,
    without_derived_watts,
)
from catch.analytics.piece_intervals import summarize_intervals, validate_intervals, with_derived_interval_watts
from catch.analytics.units import KG_PER_LB, body_mass_kg, kg_from_lb


@pytest.mark.parametrize(
    "pace_s, watts",
    [(120.0, 202.546), (110.0, 262.960), (105.0, 302.343), (100.0, 350.0), (105.3, 299.766), (90.0, 480.110), (240.0, 25.318)],
)
def test_concept2_pace_to_watts(pace_s, watts):
    assert watts_from_pace(pace_s) == pytest.approx(watts, abs=1e-3)
    assert pace_from_watts(watts_from_pace(pace_s)) == pytest.approx(pace_s)


@pytest.mark.parametrize("bad", [0, -105.0, float("nan"), float("inf"), None])
def test_zero_negative_or_non_finite_pace_is_refused(bad):
    with pytest.raises(ValueError):
        watts_from_pace(bad)


def test_full_precision_is_kept_and_only_rounded_for_display():
    assert watts_from_pace(105.3) != round(watts_from_pace(105.3))
    assert round(watts_from_pace(105.3)) == 300


def test_weight_adjusted_power_known_values():
    assert weight_adjusted_power(302.343, 80.0) == pytest.approx(16.285, abs=1e-3)
    assert weight_adjusted_power(302.343, 70.0) == pytest.approx(17.801, abs=1e-3)
    assert weight_adjusted_power(350.0, 100.0) == pytest.approx(350.0 / 100 ** (2 / 3))
    # Heavier athlete, same watts → lower score; but less of a penalty than W/kg (exponent 2/3 < 1).
    assert weight_adjusted_power(300.0, 90.0) < weight_adjusted_power(300.0, 70.0)
    assert weight_adjusted_power(300.0, 90.0) / weight_adjusted_power(300.0, 70.0) > w_per_kg(300.0, 90.0) / w_per_kg(300.0, 70.0)


@pytest.mark.parametrize("watts, kg", [(None, 80.0), (300.0, None), (300.0, 0.0), (300.0, -70.0), (0.0, 80.0), (float("nan"), 80.0), (300.0, float("inf"))])
def test_missing_zero_or_invalid_inputs_give_no_value(watts, kg):
    assert weight_adjusted_power(watts, kg) is None
    assert w_per_kg(watts, kg) is None


def test_pounds_are_converted_to_kilograms_before_any_calculation():
    assert KG_PER_LB == 0.45359237
    assert kg_from_lb(176.37) == pytest.approx(80.0, abs=1e-3)
    assert body_mass_kg(176.37, "lb") == pytest.approx(80.0, abs=1e-3) and body_mass_kg(80.0, "kg") == 80.0
    assert weight_adjusted_power(302.343, body_mass_kg(176.37, "lb")) == pytest.approx(16.285, abs=1e-3)
    for bad in (0, -1, float("nan")):
        with pytest.raises(ValueError):
            kg_from_lb(bad)
    with pytest.raises(ValueError):
        body_mass_kg(80.0, "stone")


# --- which weigh-in belongs to a performance ------------------------------------------------------


D = date(2026, 6, 15)


def test_weight_on_or_before_the_day_wins_over_one_after():
    days, kgs = [D - timedelta(days=3), D + timedelta(days=1)], [80.0, 78.0]
    assert weight_for_day(days, kgs, D) == (80.0, D - timedelta(days=3))


def test_same_day_weigh_in_is_used():
    assert weight_for_day([D - timedelta(days=1), D], [81.0, 80.5], D) == (80.5, D)


def test_older_than_the_window_falls_back_to_a_reading_just_after_else_none():
    old = D - timedelta(days=BEFORE_DAYS + 1)
    assert weight_for_day([old, D + timedelta(days=AFTER_DAYS)], [80.0, 79.0], D) == (79.0, D + timedelta(days=AFTER_DAYS))
    assert weight_for_day([old, D + timedelta(days=AFTER_DAYS + 1)], [80.0, 79.0], D) is None
    assert weight_for_day([D - timedelta(days=BEFORE_DAYS)], [80.0], D) == (80.0, D - timedelta(days=BEFORE_DAYS))


def test_no_weigh_ins_means_unavailable_never_today():
    assert weight_for_day([], [], D) is None


def test_implausible_readings_are_not_a_body_mass():
    assert not plausible_body_mass(0) and not plausible_body_mass(4.2) and not plausible_body_mass(None) and not plausible_body_mass(float("nan"))
    assert plausible_body_mass(64.1)


# --- split rows → watts ------------------------------------------------------------------------------


def _rows(splits_s, distance_each=500.0):
    return [{"split_index": i + 1, "distance_m": distance_each * (i + 1), "split_s": s, "rate": None, "watts": None, "hr": None} for i, s in enumerate(splits_s)]


def test_rowing_rows_get_watts_from_their_own_pace():
    rows = with_derived_watts(_rows([100.0, 105.0, 110.0, 120.0]), "rowing_erg")
    assert [round(r["watts"], 3) for r in rows] == [350.0, 302.343, 262.960, 202.546]
    assert all(r["watts_source"] == "pace" for r in rows)


def test_a_short_last_split_uses_its_own_distance():
    rows = _rows([100.0, 100.0])
    rows[1]["distance_m"] = 750.0  # 250 m in 50 s → 100 s/500 m
    rows[1]["split_s"] = 50.0
    assert row_pace_500(rows, 1) == pytest.approx(100.0)
    assert with_derived_watts(rows, "rowing_erg")[1]["watts"] == pytest.approx(350.0)


def test_a_time_only_row_has_no_pace_no_derived_watts_and_no_false_mismatch():
    rows = [{"split_index": 1, "distance_m": None, "split_s": 300.0, "rate": 24, "watts": 210.0, "hr": None}]
    assert row_pace_500(rows, 0) is None
    assert validate_splits(rows, None, 300.0, "rowing_erg")["ok"]  # used to be flagged: a 5:00 row assumed to be 500 m "implies" 13 W
    out = with_derived_watts(rows, "rowing_erg")
    assert out[0]["watts"] == 210.0 and out[0]["watts_source"] == "entered"


def test_contradictory_typed_watts_are_flagged_and_if_forced_the_split_wins_but_the_typed_value_is_kept():
    rows = _rows([105.0, 105.0, 105.0, 105.0])
    rows[0]["watts"] = 250.0
    rows[1]["watts"] = 302.0  # the PM5's own rounding: fine
    result = validate_splits(rows, 2000.0, 420.0, "rowing_erg")
    assert [i["split_index"] for i in result["issues"] if i["field"] == "watts"] == [1]
    assert "302 W" in result["issues"][0]["message"]
    saved = with_derived_watts(rows, "rowing_erg")
    assert saved[0]["watts"] == pytest.approx(302.343, abs=1e-3) and saved[0]["watts_entered"] == 250.0
    assert "watts_entered" not in saved[1]


def test_derivation_is_idempotent_and_an_edited_split_re_derives_without_being_flagged():
    once = with_derived_watts(_rows([105.0, 110.0]), "rowing_erg")
    assert with_derived_watts(once, "rowing_erg") == once
    once[0]["split_s"] = 100.0  # the athlete edits the split; the stored watts were Catch's own, so not "contradictory"
    assert validate_splits(once, None, None, "rowing_erg")["ok"]
    assert with_derived_watts(once, "rowing_erg")[0]["watts"] == pytest.approx(350.0)


def test_bike_rows_never_use_the_rowing_formula():
    rows = [{"split_index": 1, "distance_m": 1000.0, "split_s": 100.0, "rate": 90, "watts": 260.0, "hr": None},
            {"split_index": 2, "distance_m": 2000.0, "split_s": 100.0, "rate": 90, "watts": None, "hr": None}]
    out = with_derived_watts(rows, "bike")
    assert out[0]["watts"] == 260.0 and out[1]["watts"] is None
    assert validate_splits(rows, 2000.0, 200.0, "bike")["ok"]  # 999 W at this pace would also be fine: no pace check on a bike
    watts, basis = piece_avg_watts("bike", 100.0, out)
    assert watts == 260.0 and basis == "entered"
    assert piece_avg_watts("bike", 100.0, [{"split_s": 100.0, "watts": None}]) == (None, None)


def test_switching_a_piece_to_bike_drops_rowing_derived_watts_and_restores_typed_ones():
    rowing = with_derived_watts(_rows([105.0]) + [], "rowing_erg")
    rowing[0]["watts_entered"] = 250.0
    back = without_derived_watts(rowing)
    assert back[0]["watts"] == 250.0 and "watts_source" not in back[0] and "watts_entered" not in back[0]
    assert with_derived_watts(back, "bike")[0]["watts"] == 250.0


def test_piece_average_watts_come_from_the_average_pace_not_a_mean_of_split_watts():
    rows = with_derived_watts(_rows([100.0, 120.0]), "rowing_erg")  # 350 W and 202.5 W
    agg = aggregate_from_splits(rows, "rowing_erg")
    assert agg["avg_split_s"] == pytest.approx(110.0)
    assert agg["avg_watts"] == pytest.approx(262.960, abs=1e-3) and agg["avg_watts_basis"] == "pace"
    assert agg["avg_watts"] < (350.0 + 202.546) / 2  # the old plain mean overstated it (power is cubic in pace)


def test_a_totals_only_piece_gets_watts_from_its_totals():
    rows = with_derived_watts(totals_only_splits(2000.0, 420.0, 30.0, None), "rowing_erg")
    assert rows[0]["watts"] == pytest.approx(302.343, abs=1e-3)
    assert piece_avg_watts("rowing_erg", 105.0, rows) == (pytest.approx(302.343, abs=1e-3), "pace")


def test_a_duration_only_rowing_piece_keeps_the_screens_average_watts():
    rows = [{"split_index": 1, "distance_m": None, "split_s": 1800.0, "rate": 20, "watts": None, "hr": None}]
    assert piece_avg_watts("rowing_erg", None, rows, entered=215.0) == (215.0, "entered")
    assert piece_avg_watts("rowing_erg", None, rows) == (None, None)


# --- intervals ---------------------------------------------------------------------------------------


def _interval(d, t, **kw):
    return {"position": 0, "target_type": "distance", "work_distance_m": d, "work_duration_s": t, "rest_duration_s": None, "avg_split_s": None,
            "avg_watts": None, "avg_rate": None, "avg_hr": None, "max_hr": None, "calories": None, "notes": None, **kw}


def test_interval_watts_from_pace_and_the_set_from_the_total_pace():
    rows = with_derived_interval_watts([_interval(500, 100.0), _interval(500, 120.0)], "rowing_erg")
    assert rows[0]["avg_watts"] == pytest.approx(350.0) and rows[1]["avg_watts"] == pytest.approx(202.546, abs=1e-3)
    summary = summarize_intervals(rows, "rowing_erg")
    assert summary["avg_split_s"] == pytest.approx(110.0)
    assert summary["avg_watts"] == pytest.approx(262.960, abs=1e-3)  # not the time-weighted mean of 350 and 202.5
    # Weight-adjusted for the set is from the set's own watts, not an average of the intervals' scores.
    kg = 80.0
    per_interval_mean = sum(weight_adjusted_power(r["avg_watts"], kg) for r in rows) / 2
    assert weight_adjusted_power(summary["avg_watts"], kg) != pytest.approx(per_interval_mean)


def test_a_typed_interval_watts_that_contradicts_its_pace_is_flagged_but_bike_is_not():
    rows = [{**_interval(500, 105.0, avg_watts=250.0), "position": 0}]
    assert any(i["field"] == "avg_watts" for i in validate_intervals(rows, "rowing_erg")["issues"])
    assert validate_intervals(rows, "bike")["ok"]
    assert with_derived_interval_watts(rows, "bike")[0]["avg_watts"] == 250.0


def test_nan_never_appears():
    rows = with_derived_watts(_rows([0.0]), "rowing_erg")
    assert rows[0].get("watts") is None or math.isfinite(rows[0]["watts"])
