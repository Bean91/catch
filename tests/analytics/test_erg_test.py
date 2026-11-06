from __future__ import annotations

from datetime import date

import pytest

from catch.analytics.erg_test import actual_splits, detect_test_type, pacing_analysis, pacing_plan, project_time


def test_detect_test_type_matches_standard_distance():
    assert detect_test_type(2000.0, 420.0, 32.0) == "2000m"
    assert detect_test_type(1998.0, 419.0, 32.0) == "2000m"  # within 2% tolerance


def test_detect_test_type_matches_30min_r20_only_under_the_rate_cap():
    assert detect_test_type(None, 1800.0, 19.5) == "30min_r20"
    assert detect_test_type(None, 1800.0, 28.0) is None  # same duration, not a steady r20


def test_detect_test_type_returns_none_for_nothing_standard():
    assert detect_test_type(3333.0, 900.0, 30.0) is None


def test_pacing_plan_splits_sum_exactly_to_goal_time():
    for style in ("even", "fast_start_settle", "negative_split"):
        plan = pacing_plan(2000.0, 420.0, style)
        assert sum(s["target_split_s"] for s in plan["splits"]) == pytest.approx(420.0)
        assert plan["splits"][-1]["target_cum_s"] == pytest.approx(420.0)


def test_pacing_plan_even_style_has_identical_splits():
    plan = pacing_plan(2000.0, 400.0, "even")
    assert all(s["target_split_s"] == pytest.approx(100.0) for s in plan["splits"])


def test_pacing_plan_fast_start_settle_starts_faster_than_it_ends():
    plan = pacing_plan(2000.0, 420.0, "fast_start_settle")
    assert plan["splits"][0]["target_split_s"] < plan["splits"][-1]["target_split_s"]


def test_pacing_plan_negative_split_ends_faster_than_it_starts():
    plan = pacing_plan(2000.0, 420.0, "negative_split")
    assert plan["splits"][-1]["target_split_s"] < plan["splits"][0]["target_split_s"]


def test_pacing_plan_rejects_unknown_style():
    with pytest.raises(ValueError):
        pacing_plan(2000.0, 420.0, "sprint_throughout")


def _points(total_distance: float, total_time: float, n: int = 40) -> list[dict]:
    """Even-paced synthetic stroke stream for pacing_analysis tests."""
    return [{"distance_cum": total_distance * i / n, "t_cum": total_time * i / n} for i in range(1, n + 1)]


def test_actual_splits_of_an_even_piece_are_all_equal():
    points = _points(2000.0, 400.0)
    splits = actual_splits(points, 2000.0)
    assert len(splits) == 4
    assert all(s["actual_split_s"] == pytest.approx(100.0, abs=1.0) for s in splits)


def test_pacing_analysis_flags_a_slow_segment_as_the_worst_split():
    # Even first 1500m, then a slow last 500m — the last split should read out as the worst.
    even = [{"distance_cum": 1500.0 * i / 30, "t_cum": 300.0 * i / 30} for i in range(1, 31)]
    slow_tail = [{"distance_cum": 1500.0 + 500.0 * i / 10, "t_cum": 300.0 + 150.0 * i / 10} for i in range(1, 11)]
    analysis = pacing_analysis(even + slow_tail, 2000.0)
    assert analysis["worst_split_vs_even"]["split_index"] == 4
    assert analysis["worst_split_vs_even"]["seconds_lost_vs_even"] > 0


def test_pacing_analysis_compares_against_a_saved_plan():
    plan = pacing_plan(2000.0, 400.0, "even")
    points = _points(2000.0, 410.0)  # 10s slower than planned, evenly
    analysis = pacing_analysis(points, 2000.0, plan)
    assert analysis["vs_plan"] is not None
    assert all(row["delta_s"] > 0 for row in analysis["vs_plan"])


def test_project_time_refuses_with_fewer_than_three_points():
    history = [(date(2026, 1, 1), 420.0), (date(2026, 2, 1), 415.0)]
    result = project_time(history, date(2026, 6, 1))
    assert result["value"] is None
    assert "3" in result["explanation"]
    assert len(result["inputs"]) == 2


def test_project_time_extrapolates_a_clean_linear_improvement():
    history = [(date(2026, 1, 1), 420.0), (date(2026, 2, 1), 410.0), (date(2026, 3, 1), 400.0)]
    result = project_time(history, date(2026, 4, 1))
    assert result["value"] is not None
    assert result["value"] < 400.0  # trend keeps improving
    assert result["range"][0] <= result["value"] <= result["range"][1]
    assert result["n_points"] == 3
