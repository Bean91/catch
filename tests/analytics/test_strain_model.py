"""Session 32: one strain curve over one load sum (catch/analytics/strain.py's day_load_strain). Hand-computed:
strain = 2.54 x ln(1 + load); walking TRIMP/min at 25 % HRR = 0.25 x 0.64 x e^(1.92 x 0.25) = 0.2586; strength REF = 70."""

from __future__ import annotations

import math

import pytest

from catch.analytics.defaults import DEFAULT_SETTINGS as S
from catch.analytics.load import training_load
from catch.analytics.strain import (
    daily_activity_trimp,
    day_load_strain,
    muscular_trimp_equivalent,
    strain_from_load,
    strength_baseline_au,
    strength_session_load,
)

WALK = 0.25 * 0.64 * math.exp(1.92 * 0.25)


def strain(load):
    return 2.54 * math.log1p(load)


def cardio(load, cid=1):
    return {"canonical_id": cid, "kind": "cardio", "load": load, "muscular_load": 0.0}


def lift(load, muscular, cid=2):
    return {"canonical_id": cid, "kind": "strength", "load": load, "muscular_load": muscular}


NO_MOVEMENT = daily_activity_trimp(None, None, S)


def test_rest_day_is_only_daily_movement():
    move = daily_activity_trimp(8000, None, S)
    out = day_load_strain([], move, S)
    assert out["load"] == pytest.approx(80 * WALK)
    assert out["value"] == pytest.approx(strain(80 * WALK))
    assert out["shares"]["daily_activity"] == pytest.approx(1.0)


def test_an_easy_hour_on_the_erg_is_its_trimp_and_nothing_more():
    out = day_load_strain([cardio(77.0)], NO_MOVEMENT, S)
    assert out["value"] == pytest.approx(strain(77.0))  # ~11.1, the documented "steady hour"
    assert out["muscular_load"] == 0.0


def test_two_rows_sum_their_load_before_the_curve_never_their_strains():
    out = day_load_strain([cardio(60.0, 1), cardio(60.0, 2)], NO_MOVEMENT, S)
    assert out["value"] == pytest.approx(strain(120.0))
    assert out["value"] < 2 * strain(60.0)  # adding two 0-21 scores would have been ~20.9
    assert [s["share"] for s in out["sessions"]] == [pytest.approx(0.5), pytest.approx(0.5)]


def test_a_heavy_lift_without_hr_or_rpe_still_counts_relative_to_the_athletes_own_norm():
    baseline, source = strength_baseline_au([3000, 3200, 2800, 3100], S)
    assert (baseline, source) == (3050.0, "personal")
    eq = muscular_trimp_equivalent(4575.0, baseline, S)  # 1.5 typical sessions
    assert eq == pytest.approx(105.0)
    load, method = strength_session_load(None, None, eq)
    assert (load, method) == (pytest.approx(105.0), "muscular")
    assert day_load_strain([lift(load, eq)], NO_MOVEMENT, S)["value"] == pytest.approx(strain(105.0))


def test_lifting_with_heart_rate_adds_both_and_with_only_rpe_takes_the_larger():
    assert strength_session_load(30.0, None, 70.0) == (pytest.approx(100.0), "hr_plus_muscular")
    assert strength_session_load(None, 80.0, 70.0) == (pytest.approx(80.0), "srpe")
    assert strength_session_load(None, 50.0, 70.0) == (pytest.approx(70.0), "muscular")


def test_absolute_kilograms_cannot_swamp_a_rowing_day():
    # A heavy lifter (typical session 20,000 AU) and a light lifter (2,000 AU) each doing their normal session count the same,
    # and a mis-typed monster session is capped at 2.5 typical sessions.
    heavy = muscular_trimp_equivalent(20000, strength_baseline_au([20000] * 4, S)[0], S)
    light = muscular_trimp_equivalent(2000, strength_baseline_au([2000] * 4, S)[0], S)
    assert heavy == light == pytest.approx(70.0)
    assert muscular_trimp_equivalent(10**7, 20000, S) == pytest.approx(2.5 * 70.0)


def test_a_new_lifter_uses_the_documented_default_until_three_sessions():
    assert strength_baseline_au([5000, 5000], S) == (4000.0, "default")
    assert muscular_trimp_equivalent(4000, 4000.0, S) == pytest.approx(70.0)


def test_row_plus_lift_plus_walking_is_one_sum_and_the_parts_share_the_headline():
    move = daily_activity_trimp(6000, None, S)
    out = day_load_strain([cardio(77.0, 1), lift(70.0, 70.0, 2)], move, S)
    total = 77.0 + 70.0 + 60 * WALK
    assert out["load"] == pytest.approx(total) and out["value"] == pytest.approx(strain(total))
    assert sum(out["shares"].values()) == pytest.approx(1.0)
    assert out["shares"]["muscular"] == pytest.approx(70.0 / total)


def test_a_session_with_no_data_and_no_movement_is_insufficient_not_zero():
    out = day_load_strain([{"canonical_id": 9, "kind": "cardio", "load": None}], NO_MOVEMENT, S)
    assert out["value"] is None and out["band"] == "insufficient_data"


def test_the_curve_is_capped_at_21():
    assert strain_from_load(10**6, S) == 21.0 and strain_from_load(0, S) == 0.0


def test_acute_and_chronic_load_consume_the_day_load_series():
    # A strength-only week (70 a day, three days) now registers training load; before session 32 it entered as 0.
    series = [0, 70, 0, 70, 0, 70, 0]
    load = training_load(series, S)
    assert load["components"][0]["acute_7d"] > 0
    rest_only = training_load([0] * 7, S)
    assert rest_only["components"][0]["acute_7d"] == 0
