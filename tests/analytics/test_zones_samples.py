from __future__ import annotations

from catch.analytics.zones_samples import (
    banister_trimp_from_samples,
    detect_trailing_idle,
    drop_dropouts,
    power_time_in_zone_seconds,
    session_label,
    smooth,
    time_in_zone_seconds,
)
from catch.analytics.zones import ZONE_ORDER

MAX_HR = 190.0
RESTING_HR = 50.0
WARMUP_HR = 118.0  # UT2 (>=60% of 190=114, <70%=133)
HARD_HR = 180.0  # AN (>=93% of 190=176.7)


def _flat(hr: float, seconds: int) -> list[float]:
    return [hr] * seconds


def _quality_bar_profile() -> list[float]:
    """20 min warm-up, 10 min at ~95% max HR, 25 min cool-down — the task's own motivating
    fixture: average-HR classification would call this UT2 (its mean is well under the UT1
    boundary), but 10 real minutes at AN must dominate the label and the strain."""
    return _flat(WARMUP_HR, 20 * 60) + _flat(HARD_HR, 10 * 60) + _flat(WARMUP_HR, 25 * 60)


def test_quality_bar_profile_label_is_never_ut2():
    profile = _quality_bar_profile()
    zones = time_in_zone_seconds(smooth(profile), MAX_HR)
    label = session_label(zones, moving_time_s=len(profile))
    assert not label.startswith("UT2")
    assert label.startswith("AN") or label.startswith("TR")


def test_quality_bar_profile_strain_exceeds_a_steady_ut2_piece_of_the_same_average_hr():
    profile = _quality_bar_profile()
    avg_hr = sum(profile) / len(profile)
    assert avg_hr < 133  # confirms the average alone would read as UT2 — the whole point

    steady_ut2 = _flat(avg_hr, 55 * 60)

    profile_trimp = banister_trimp_from_samples(profile, RESTING_HR, MAX_HR)
    steady_trimp = banister_trimp_from_samples(steady_ut2, RESTING_HR, MAX_HR)
    assert profile_trimp > steady_trimp


def test_time_in_zone_sums_real_seconds_not_whole_session_average():
    profile = _quality_bar_profile()
    zones = time_in_zone_seconds(profile, MAX_HR)
    assert zones["AN"] == 600.0  # exactly the 10 real minutes, not a share of the average
    assert zones["UT2"] == 45 * 60.0


def test_drop_dropouts_removes_zero_and_long_flatlines():
    samples = [120.0] * 10 + [0.0] * 5 + [150.0] * 40  # a 40s flatline at 150 is a dropout
    cleaned = drop_dropouts(samples, flatline_run_s=30)
    assert cleaned[10:15] == [None] * 5  # the zero run
    assert cleaned[15:55] == [None] * 40  # the stuck-sensor run
    assert cleaned[:10] == [120.0] * 10  # a short, real plateau survives


def test_smooth_skips_dropouts_in_its_window():
    samples = [100.0, 100.0, None, 100.0, 100.0]
    smoothed = smooth(samples, window_s=5)
    assert smoothed[2] == 100.0  # the None in the middle doesn't drag the average down


def test_detect_trailing_idle_flags_a_long_trailing_zero_cadence_run():
    cadence = [20.0] * 600 + [0.0] * 150
    assert detect_trailing_idle(cadence, min_idle_s=120) == 150.0


def test_detect_trailing_idle_ignores_a_short_pause():
    cadence = [20.0] * 600 + [0.0] * 30
    assert detect_trailing_idle(cadence, min_idle_s=120) == 0.0


def test_detect_trailing_idle_returns_zero_with_no_movement_signal_at_all():
    assert detect_trailing_idle([None] * 100) == 0.0


def test_power_time_in_zone_mirrors_hr_zone_math():
    totals = power_time_in_zone_seconds([250.0] * 600, watts_2k=250.0)
    assert sum(totals.values()) == 600.0
    assert all(z in totals for z in ZONE_ORDER)


def test_session_label_falls_back_to_largest_zone_when_nothing_clears_the_floor():
    zones = {z: 0.0 for z in ZONE_ORDER}
    zones["UT1"] = 5.0  # far under any floor for a long session
    label = session_label(zones, moving_time_s=10000.0)
    assert label.startswith("UT1")


def test_session_label_prefers_the_higher_intensity_reading_between_hr_and_power():
    hr_zones = {z: 0.0 for z in ZONE_ORDER}
    hr_zones["UT1"] = 600.0
    power_zones = {z: 0.0 for z in ZONE_ORDER}
    power_zones["TR"] = 600.0
    label = session_label(hr_zones, moving_time_s=600.0, power_zone_seconds=power_zones)
    assert label.startswith("TR")
