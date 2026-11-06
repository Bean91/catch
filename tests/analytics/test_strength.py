from __future__ import annotations


from catch.analytics.strength import (
    PrResult,
    WorkingSet,
    cardio_muscular_au,
    detect_pr,
    distribute_to_muscles,
    epley_e1rm,
    intensity_factor,
    normalize_muscle_au,
    reps_to_failure,
    set_muscular_au,
)


def test_epley_1rm_basic():
    assert abs(epley_e1rm(100.0, 1) - 103.33) < 0.01


def test_epley_caps_at_10_reps():
    # 15 reps at 50kg should produce the same e1RM as 10 reps at 50kg — capped, not extrapolated.
    assert epley_e1rm(50.0, 15) == epley_e1rm(50.0, 10)
    assert epley_e1rm(50.0, 10) == 50.0 * (1 + 10 / 30.0)


def test_epley_zero_or_negative_inputs_are_zero():
    assert epley_e1rm(0.0, 5) == 0.0
    assert epley_e1rm(50.0, 0) == 0.0


def test_reps_to_failure_prefers_rir():
    assert reps_to_failure(5, rir=2, rpe=9) == 2.0


def test_reps_to_failure_falls_back_to_rpe():
    assert reps_to_failure(5, rir=None, rpe=9) == 1.0
    assert reps_to_failure(5, rir=None, rpe=10) == 0.0


def test_reps_to_failure_default_when_neither_given():
    assert reps_to_failure(5, rir=None, rpe=None) == 2.0


def test_intensity_factor_decreases_as_reps_to_failure_grows():
    near_failure = intensity_factor(1)
    far_from_failure = intensity_factor(20)
    assert near_failure > far_from_failure
    assert 0.0 < far_from_failure < near_failure <= 1.0


def test_set_muscular_au_warmup_is_zero():
    s = WorkingSet(exercise_id=1, date="2026-11-01", reps=10, effective_load_kg=40.0, set_type="warmup")
    assert set_muscular_au(s) == 0.0


def test_set_muscular_au_scales_with_load_and_reps():
    light = WorkingSet(exercise_id=1, date="2026-11-01", reps=5, effective_load_kg=20.0, rir=5)
    heavy = WorkingSet(exercise_id=1, date="2026-11-01", reps=5, effective_load_kg=100.0, rir=1)
    assert set_muscular_au(heavy) > set_muscular_au(light)


def test_set_muscular_au_rewards_proximity_to_failure_at_same_load_and_reps():
    easy = WorkingSet(exercise_id=1, date="2026-11-01", reps=8, effective_load_kg=60.0, rir=8)
    hard = WorkingSet(exercise_id=1, date="2026-11-01", reps=8, effective_load_kg=60.0, rir=0)
    assert set_muscular_au(hard) > set_muscular_au(easy)


def test_set_muscular_au_no_load_is_zero():
    s = WorkingSet(exercise_id=1, date="2026-11-01", reps=10, effective_load_kg=None)
    assert set_muscular_au(s) == 0.0


def test_distribute_to_muscles_primary_full_secondary_half():
    out = distribute_to_muscles(100.0, ["chest"], ["triceps", "shoulders"])
    assert out["chest"] == 100.0
    assert out["triceps"] == 50.0
    assert out["shoulders"] == 50.0


def test_distribute_to_muscles_no_division_across_multiple_primaries():
    out = distribute_to_muscles(100.0, ["quadriceps", "glutes"], [])
    assert out["quadriceps"] == 100.0
    assert out["glutes"] == 100.0


def test_normalize_muscle_au_cold_start_uses_raw_value():
    assert normalize_muscle_au(500.0, []) == 500.0


def test_normalize_muscle_au_clamps_spike_above_baseline():
    baseline = [100.0] * 28
    # 10x a normal day should clamp at 2x baseline, not blow through unclamped.
    assert normalize_muscle_au(1000.0, baseline) == 200.0


def test_normalize_muscle_au_clamps_dip_below_baseline():
    baseline = [100.0] * 28
    assert normalize_muscle_au(1.0, baseline) == 40.0


def test_normalize_muscle_au_near_baseline_passes_through():
    baseline = [100.0] * 28
    assert abs(normalize_muscle_au(110.0, baseline) - 110.0) < 1e-9


def test_cardio_muscular_au_is_small_relative_to_a_real_lifting_session():
    # ~90s above threshold at 300W during an all-out erg piece.
    erg_sprint_au = cardio_muscular_au(90.0, 300.0)
    # a single hard working set of squats.
    lifting_set = WorkingSet(exercise_id=1, date="2026-11-01", reps=5, effective_load_kg=120.0, rir=1)
    assert erg_sprint_au < set_muscular_au(lifting_set)


def test_cardio_muscular_au_zero_when_no_time_above_threshold():
    assert cardio_muscular_au(0.0, 300.0) == 0.0


def test_cardio_muscular_au_moderate_tier_is_nonzero_and_well_under_the_sprint_rate():
    # A full 30-minute piece held steadily in the 55-110%-of-threshold band (e.g. a hard
    # steady row or a ride held at FTP) now contributes something — before the moderate tier
    # existed, this landed at exactly 0 AU since none of it crossed the old 110% sprint bar.
    moderate_only = cardio_muscular_au(0.0, 300.0, seconds_moderate=1800.0)
    assert moderate_only > 0.0
    # Per-second, moderate effort earns much less than sprint effort, not just a smaller window.
    sprint_equivalent = cardio_muscular_au(1800.0, 300.0)
    assert moderate_only < sprint_equivalent


def test_cardio_muscular_au_moderate_tier_still_small_relative_to_a_real_lifting_session():
    # A full hour held at threshold must still read as clearly less muscular load than a
    # single hard working set, same "default low" guarantee as the sprint tier.
    hour_at_threshold_au = cardio_muscular_au(0.0, 250.0, seconds_moderate=3600.0)
    lifting_set = WorkingSet(exercise_id=1, date="2026-11-01", reps=5, effective_load_kg=120.0, rir=1)
    assert hour_at_threshold_au < set_muscular_au(lifting_set)


def test_detect_pr_first_ever_set_is_both_prs():
    s = WorkingSet(exercise_id=1, date="2026-11-01", reps=5, effective_load_kg=100.0)
    result = detect_pr(s, [])
    assert result == PrResult(True, True)


def test_detect_pr_rep_pr_requires_beating_same_rep_count():
    history = [WorkingSet(exercise_id=1, date="2026-10-01", reps=5, effective_load_kg=90.0)]
    heavier_same_reps = WorkingSet(exercise_id=1, date="2026-11-01", reps=5, effective_load_kg=95.0)
    assert detect_pr(heavier_same_reps, history).is_rep_pr

    lighter_same_reps = WorkingSet(exercise_id=1, date="2026-11-01", reps=5, effective_load_kg=80.0)
    assert not detect_pr(lighter_same_reps, history).is_rep_pr


def test_detect_pr_e1rm_pr_can_come_from_different_rep_count():
    history = [WorkingSet(exercise_id=1, date="2026-10-01", reps=5, effective_load_kg=90.0)]
    # a heavy double can beat a lighter set-of-5's e1RM even though the rep count differs.
    heavy_double = WorkingSet(exercise_id=1, date="2026-11-01", reps=2, effective_load_kg=100.0)
    result = detect_pr(heavy_double, history)
    assert result.is_e1rm_pr


def test_detect_pr_warmup_never_counts():
    history = [WorkingSet(exercise_id=1, date="2026-10-01", reps=5, effective_load_kg=90.0)]
    warmup = WorkingSet(exercise_id=1, date="2026-11-01", reps=5, effective_load_kg=200.0, set_type="warmup")
    assert detect_pr(warmup, history) == PrResult(False, False)


def test_detect_pr_ignores_history_warmups():
    history = [WorkingSet(exercise_id=1, date="2026-10-01", reps=5, effective_load_kg=200.0, set_type="warmup")]
    working = WorkingSet(exercise_id=1, date="2026-11-01", reps=5, effective_load_kg=100.0)
    # the warmup shouldn't block a working-set PR just because its number happens to be bigger.
    assert detect_pr(working, history).is_rep_pr
