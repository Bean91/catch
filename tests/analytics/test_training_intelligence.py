from __future__ import annotations

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.analytics.training_intelligence import (
    _BANNED_PHRASES,
    compare_equivalent_pieces,
    confidence_level,
    evaluate_data_quality_warning,
    evaluate_overload_warning,
    evaluate_recovery_suggestion,
    evaluate_training_suggestion,
    training_insights,
    training_profile,
)

SETTINGS = DEFAULT_SETTINGS
TI = SETTINGS["training_intelligence"]


def _row(d: str, duration_s: float | None, distance_m: float | None, rate: float | None = None, drag: int | None = None) -> dict:
    return {"date": d, "duration_s": duration_s, "distance_m": distance_m, "avg_stroke_rate": rate, "drag_factor": drag}


# --- confidence_level ------------------------------------------------------------------------


def test_confidence_insufficient_below_min_history_days():
    assert confidence_level(TI["data_quality_min_history_days"] - 1, 10, SETTINGS) == "insufficient_data"


def test_confidence_capped_by_weaker_of_days_and_points():
    # Plenty of days, but too few points of this specific type -> capped at "low".
    assert confidence_level(TI["confidence_days_high"], 1, SETTINGS) == "low"
    # Plenty of points, but only "medium" days -> capped at "medium".
    assert confidence_level(TI["confidence_days_medium"], TI["confidence_pieces_high"], SETTINGS) == "medium"


def test_confidence_high_requires_both():
    assert confidence_level(TI["confidence_days_high"], TI["confidence_pieces_high"], SETTINGS) == "high"


# --- compare_equivalent_pieces -----------------------------------------------------------------


def test_fewer_than_minimum_points_refuses_trend_like_project_time():
    rows = [_row("2026-01-01", 420, 2000), _row("2026-02-01", 410, 2000)]
    result = compare_equivalent_pieces("2000m", rows, SETTINGS)
    assert result["trend"]["value"] is None
    assert "Need at least" in result["trend"]["explanation"]
    assert result["n_points"] == 2


def test_recent_improvement_at_equal_rate_is_likely_real():
    rows = [
        _row("2026-01-01", 420, 2000, rate=30),
        _row("2026-02-01", 415, 2000, rate=30),
        _row("2026-03-01", 405, 2000, rate=29),
    ]
    result = compare_equivalent_pieces("2000m", rows, SETTINGS)
    assert result["rate_note"] is not None
    assert "likely real improvement" in result["rate_note"]


def test_recent_improvement_at_materially_higher_rate_is_flagged_as_possible_pacing_change():
    rows = [
        _row("2026-01-01", 420, 2000, rate=28),
        _row("2026-02-01", 415, 2000, rate=28),
        _row("2026-03-01", 400, 2000, rate=34),  # ~21% rate increase alongside the "improvement"
    ]
    result = compare_equivalent_pieces("2000m", rows, SETTINGS)
    assert "possible pacing/rate change" in result["rate_note"]


def test_duration_based_type_compares_distance_not_pace():
    rows = [_row("2026-01-01", 1800, 7000), _row("2026-02-01", 1800, 7100), _row("2026-03-01", 1800, 7250)]
    result = compare_equivalent_pieces("30min_r20", rows, SETTINGS)
    assert result["kind"] == "duration"
    assert result["best"]["value"] == 7250  # higher distance covered in the same fixed duration wins


def test_unrecognized_test_type_rows_are_excluded_not_guessed():
    rows = [_row("2026-01-01", 500, 1234), _row("2026-02-01", 510, 1234)]
    result = compare_equivalent_pieces("custom", rows, SETTINGS)
    assert result["n_points"] == 0
    assert result["best"] is None


def test_drag_factor_spread_is_annotated_not_rebucketed():
    rows = [
        _row("2026-01-01", 420, 2000, rate=30, drag=108),
        _row("2026-02-01", 415, 2000, rate=30, drag=115),
        _row("2026-03-01", 405, 2000, rate=30, drag=108),
    ]
    result = compare_equivalent_pieces("2000m", rows, SETTINGS)
    assert result["n_points"] == 3  # still one bucket
    assert result["drag_note"] is not None


# --- evaluate_data_quality_warning ------------------------------------------------------------


def test_data_quality_fires_below_min_history():
    result = evaluate_data_quality_warning({"history_days": 1}, SETTINGS)
    assert result is not None
    assert result["rule_key"] == "data_quality:insufficient_history"
    assert result["confidence"] == "insufficient_data"


def test_data_quality_fires_on_missing_hr_share():
    context = {"history_days": 365, "missing_hr_pct": TI["data_quality_missing_hr_pct_threshold"], "missing_hr_lookback_n": 10}
    result = evaluate_data_quality_warning(context, SETTINGS)
    assert result is not None
    assert result["rule_key"] == "data_quality:missing_hr"


def test_data_quality_silent_when_history_and_hr_are_fine():
    context = {"history_days": 365, "missing_hr_pct": 0.0}
    assert evaluate_data_quality_warning(context, SETTINGS) is None


# --- evaluate_training_suggestion suppression matrix -------------------------------------------


def _base_training_context(**overrides) -> dict:
    base = {
        "illness": {"level": "none"},
        # A real, physiologically-backed green reading — band alone ("not red") is no longer
        # enough to fire a load-increasing suggestion; see evaluate_training_suggestion's own
        # suppression matrix.
        "recovery": {"value": 75, "band": "green", "components": [{"metric": "hrv", "value": 70}, {"metric": "resting_hr", "value": 80}]},
        "load": {"band": "optimal"},
        "niggle_streak_days": 0,
        "next_event": None,
        "sessions_this_week": 1,
        "history_days": TI["confidence_days_medium"],
    }
    base.update(overrides)
    return base


def test_training_suggestion_fires_when_nothing_is_wrong_and_under_target():
    result = evaluate_training_suggestion(_base_training_context(), SETTINGS)
    assert result is not None
    assert result["rule_key"] == "training:add_session"


def test_training_suggestion_suppressed_by_illness_watch_or_likely():
    for level in ("watch", "likely"):
        assert evaluate_training_suggestion(_base_training_context(illness={"level": level}), SETTINGS) is None


def test_training_suggestion_suppressed_by_red_recovery():
    assert evaluate_training_suggestion(_base_training_context(recovery={"band": "red"}), SETTINGS) is None


def test_training_suggestion_suppressed_by_niggle_streak_at_or_above_minimum():
    min_days = SETTINGS["niggle_flag_min_days"]
    assert evaluate_training_suggestion(_base_training_context(niggle_streak_days=min_days), SETTINGS) is None
    assert evaluate_training_suggestion(_base_training_context(niggle_streak_days=min_days - 1), SETTINGS) is not None


def test_training_suggestion_suppressed_by_caution_or_high_risk_load():
    for band in ("caution", "high_risk"):
        assert evaluate_training_suggestion(_base_training_context(load={"band": band}), SETTINGS) is None


def test_training_suggestion_suppressed_near_an_event():
    near = {"name": "Champs", "days_to_go": TI["overload_suppress_near_event_days"] - 1}
    far = {"name": "Champs", "days_to_go": TI["overload_suppress_near_event_days"] + 10}
    assert evaluate_training_suggestion(_base_training_context(next_event=near), SETTINGS) is None
    assert evaluate_training_suggestion(_base_training_context(next_event=far), SETTINGS) is not None


def test_training_suggestion_silent_once_target_already_met():
    result = evaluate_training_suggestion(_base_training_context(sessions_this_week=TI["target_sessions_per_week"]), SETTINGS)
    assert result is None


# --- evaluate_overload_warning ------------------------------------------------------------------


def test_overload_requires_sustained_not_single_day():
    n = TI["overload_min_consecutive_days"]
    threshold = TI["overload_acr_threshold"]
    one_bad_day = [threshold] + [0.9] * (n - 1)
    assert evaluate_overload_warning({"acr_recent": one_bad_day}, SETTINGS) is None
    all_bad = [threshold] * n
    assert evaluate_overload_warning({"acr_recent": all_bad}, SETTINGS) is not None


def test_overload_fires_independent_of_illness_state():
    # evaluate_overload_warning takes no illness key at all — confirms it can't be suppressed
    # by it, unlike evaluate_training_suggestion.
    n = TI["overload_min_consecutive_days"]
    context = {"acr_recent": [TI["overload_acr_threshold"]] * n, "illness": {"level": "likely"}}
    assert evaluate_overload_warning(context, SETTINGS) is not None


# --- evaluate_recovery_suggestion ----------------------------------------------------------------


def test_recovery_suggestion_fires_at_or_under_threshold():
    threshold = TI["recovery_suggestion_recovery_max"]
    assert evaluate_recovery_suggestion({"recovery": {"value": threshold, "band": "yellow"}}, SETTINGS) is not None
    assert evaluate_recovery_suggestion({"recovery": {"value": threshold + 1, "band": "green"}}, SETTINGS) is None


def test_recovery_suggestion_silent_without_a_value():
    assert evaluate_recovery_suggestion({"recovery": {"value": None, "band": "calibrating"}}, SETTINGS) is None


def test_recovery_suggestion_still_fires_but_at_low_confidence_without_a_physiological_component():
    # Caution-direction recommendations fire regardless of evidence quality (understating a
    # plausible recovery concern is the risk here) — only the confidence/wording hedge changes.
    result = evaluate_recovery_suggestion({"recovery": {"value": 10, "band": "red", "components": [{"metric": "prior_strain"}]}}, SETTINGS)
    assert result is not None
    assert result["confidence"] == "low"


def test_training_suggestion_requires_a_green_band_not_merely_not_red():
    # The exact contradiction an advisor review caught live: at recovery == recovery_suggestion_
    # recovery_max, both recovery_suggestion and (pre-fix) training_suggestion could fire at
    # once, since only a "red" band suppressed the latter. "yellow" must suppress it too.
    yellow = {"value": TI["recovery_suggestion_recovery_max"], "band": "yellow", "components": [{"metric": "hrv", "value": 60}]}
    assert evaluate_training_suggestion(_base_training_context(recovery=yellow), SETTINGS) is None


def test_training_suggestion_suppressed_without_a_physiological_recovery_component():
    # A "green" band from prior_strain/checkin alone (no HRV/RHR/sleep reading that day) isn't
    # real positive evidence that recovery is genuinely fine.
    weak = {"value": 75, "band": "green", "components": [{"metric": "prior_strain"}, {"metric": "checkin"}]}
    assert evaluate_training_suggestion(_base_training_context(recovery=weak), SETTINGS) is None


def test_training_suggestion_suppressed_below_minimum_history():
    assert evaluate_training_suggestion(_base_training_context(history_days=TI["data_quality_min_history_days"] - 1), SETTINGS) is None


def test_training_suggestion_never_fires_on_a_fresh_install():
    # No recovery/load data at all yet — the exact scenario a live smoke test caught firing a
    # false "nothing to hold you back" claim before this fix.
    fresh = {
        "illness": {"level": "none"},
        "recovery": {"value": None, "band": "calibrating", "components": []},
        "load": {"value": None, "band": "insufficient_data"},
        "niggle_streak_days": 0,
        "next_event": None,
        "sessions_this_week": 0,
        "history_days": 2,
    }
    assert evaluate_training_suggestion(fresh, SETTINGS) is None


# --- structural certainty guarantees -------------------------------------------------------------


def test_low_and_medium_confidence_bodies_are_hedged():
    result = evaluate_data_quality_warning({"history_days": 1}, SETTINGS)
    assert result["confidence"] == "insufficient_data"
    assert result["body"].startswith("Based on the data so far")


def test_high_confidence_bodies_are_not_hedged():
    result = evaluate_recovery_suggestion({"recovery": {"value": 10, "band": "red", "components": [{"metric": "hrv", "value": 20}]}}, SETTINGS)
    assert result["confidence"] == "high"
    assert not result["body"].startswith("Based on the data so far")


def test_a_present_metric_name_with_a_null_value_does_not_count_as_physiological_evidence():
    # recovery.py's own spread/baseline guards can leave a component in the list with
    # value: None (e.g. a zero-spread 60d baseline) — present by name, but it didn't actually
    # contribute to the score. Must not be treated as real evidence either direction.
    null_valued = {"value": 75, "band": "green", "components": [{"metric": "hrv", "value": None}, {"metric": "resting_hr", "value": None}]}
    assert evaluate_training_suggestion(_base_training_context(recovery=null_valued), SETTINGS) is None

    low_conf = evaluate_recovery_suggestion({"recovery": {"value": 10, "band": "red", "components": [{"metric": "hrv", "value": None}]}}, SETTINGS)
    assert low_conf["confidence"] == "low"


def test_no_evaluator_output_contains_a_banned_phrase():
    n = TI["overload_min_consecutive_days"]
    candidates = [
        evaluate_data_quality_warning({"history_days": 1}, SETTINGS),
        evaluate_data_quality_warning({"history_days": 365, "missing_hr_pct": 0.9, "missing_hr_lookback_n": 10}, SETTINGS),
        evaluate_overload_warning({"acr_recent": [TI["overload_acr_threshold"]] * n}, SETTINGS),
        evaluate_recovery_suggestion({"recovery": {"value": 5, "band": "red"}}, SETTINGS),
        evaluate_training_suggestion(_base_training_context(), SETTINGS),
    ]
    for result in candidates:
        assert result is not None
        lowered = (result["title"] + " " + result["body"]).lower()
        for phrase in _BANNED_PHRASES:
            assert phrase not in lowered


def test_insufficient_data_confidence_only_comes_from_data_quality_warning():
    # The other three evaluators never return "insufficient_data" as their own confidence —
    # they simply return None when there isn't enough to say anything (see the suppression/
    # silent-when-no-value tests above). Confirmed directly here.
    n = TI["overload_min_consecutive_days"]
    for result in (
        evaluate_overload_warning({"acr_recent": [TI["overload_acr_threshold"]] * n}, SETTINGS),
        evaluate_recovery_suggestion({"recovery": {"value": 5, "band": "red"}}, SETTINGS),
        evaluate_training_suggestion(_base_training_context(), SETTINGS),
    ):
        assert result["confidence"] != "insufficient_data"


# --- training_profile -----------------------------------------------------------------------------


def test_training_profile_all_missing_data_is_insufficient_and_explains_rather_than_silent():
    result = training_profile({}, SETTINGS)
    assert result["confidence"] == "insufficient_data"
    assert result["strengths"] == []
    assert result["weaknesses"] == []
    assert "Not enough history" in result["explanation"]


def test_training_profile_names_conflicting_signals_rather_than_inventing_one_verdict():
    components = {
        "load": {"value": 0.7, "band": "undertraining"},
        "recovery": {"value": 80, "band": "green"},
        "illness": {"level": "likely", "explanation": "deviated"},
        "history_days": 200,
        "trend_buckets": [],
    }
    result = training_profile(components, SETTINGS)
    assert "undertraining" in result["explanation"] and "likely" in result["explanation"]


def test_training_profile_strengths_and_weaknesses_tag_their_evidence():
    improving_bucket = {
        "bucket_label": "2000m",
        "kind": "distance",
        "n_points": 4,
        "trend": {"value": 400.0, "slope_s_per_day": -0.05, "explanation": "faster over time", "inputs": []},
    }
    declining_bucket = {
        "bucket_label": "5000m",
        "kind": "distance",
        "n_points": 4,
        "trend": {"value": 1100.0, "slope_s_per_day": 0.05, "explanation": "slower over time", "inputs": []},
    }
    components = {
        "load": {"value": 1.0, "band": "optimal"},
        "recovery": {"value": 70, "band": "green"},
        "illness": {"level": "none"},
        "history_days": 200,
        "trend_buckets": [improving_bucket, declining_bucket],
    }
    result = training_profile(components, SETTINGS)
    assert len(result["strengths"]) == 1 and "2000m" in result["strengths"][0]["text"]
    assert len(result["weaknesses"]) == 1 and "5000m" in result["weaknesses"][0]["text"]
    assert result["strengths"][0]["evidence"]


# --- training_insights: minimum-sample gates ------------------------------------------------------


def test_weekday_concentration_gated_by_minimum_sample():
    concentrated = {0: 4, 1: 3}  # 7 sessions, all on 2 weekdays
    assert any(i["id"] == "weekday_concentration" for i in training_insights({"weekday_counts": concentrated}, SETTINGS))
    too_few = {0: 2, 1: 2}  # only 4 total, below the gate
    assert not any(i["id"] == "weekday_concentration" for i in training_insights({"weekday_counts": too_few}, SETTINGS))


def test_weekday_concentration_silent_when_evenly_spread():
    even = {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1}
    assert not any(i["id"] == "weekday_concentration" for i in training_insights({"weekday_counts": even}, SETTINGS))


def test_consistency_gap_gated_by_minimum_days():
    assert any(i["id"] == "consistency_gap" for i in training_insights({"max_gap_days": 10}, SETTINGS))
    assert not any(i["id"] == "consistency_gap" for i in training_insights({"max_gap_days": 5}, SETTINGS))


def test_fast_start_pattern_requires_majority_of_recent_pieces():
    assert any(i["id"] == "recurring_fast_start" for i in training_insights({"fast_start_flags": [True, True, True, False]}, SETTINGS))
    assert not any(i["id"] == "recurring_fast_start" for i in training_insights({"fast_start_flags": [True, False, False]}, SETTINGS))


def test_zone_polarization_requires_material_shift():
    recent = {"UT2": 0.2, "UT1": 0.2, "AT": 0.3, "TR": 0.2, "AN": 0.1}
    baseline = {"UT2": 0.2, "UT1": 0.2, "AT": 0.3, "TR": 0.2, "AN": 0.1}
    assert not any(i["id"] == "zone_polarization" for i in training_insights({"zone_pct_recent": recent, "zone_pct_baseline": baseline}, SETTINGS))


def test_empty_context_produces_no_insights():
    assert training_insights({}, SETTINGS) == []
