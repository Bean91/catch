from __future__ import annotations

import pytest

from catch.analytics.piece_intervals import (
    derived_split_s,
    expand_repeat,
    interval_signature,
    summarize_intervals,
    validate_intervals,
)


def _row(position, **kw):
    base = {"position": position, "target_type": "distance", "work_distance_m": 500.0, "work_duration_s": None, "rest_duration_s": None}
    base.update(kw)
    return base


def test_expand_repeat_distance_with_rest_has_no_trailing_rest():
    rows = expand_repeat(4, work_distance_m=500, rest_duration_s=60)
    assert [r["position"] for r in rows] == [0, 1, 2, 3]
    assert {r["target_type"] for r in rows} == {"distance"}
    assert [r["rest_duration_s"] for r in rows] == [60, 60, 60, None]
    assert validate_intervals(rows)["ok"]


def test_expand_repeat_time_based():
    rows = expand_repeat(8, work_duration_s=60, rest_duration_s=60)
    assert len(rows) == 8 and rows[0]["target_type"] == "time" and rows[0]["work_duration_s"] == 60


@pytest.mark.parametrize("kwargs", [{}, {"work_distance_m": 500, "work_duration_s": 60}, {"work_distance_m": 0}])
def test_expand_repeat_rejects_bad_target(kwargs):
    with pytest.raises(ValueError):
        expand_repeat(4, **kwargs)


def test_expand_repeat_rejects_bad_count():
    with pytest.raises(ValueError):
        expand_repeat(0, work_distance_m=500)


def test_validate_flags_negative_missing_target_and_hr_order():
    rows = [
        _row(0, work_distance_m=-5),
        _row(1, work_distance_m=None),
        _row(2, avg_hr=150, max_hr=140),
        _row(3, target_type="bogus"),
    ]
    fields = {(i["index"], i["field"]) for i in validate_intervals(rows)["issues"]}
    assert (0, "work_distance_m") in fields
    assert (1, "work_distance_m") in fields
    assert (2, "max_hr") in fields
    assert (3, "target_type") in fields


def test_validate_flags_duplicate_and_gapped_positions():
    assert not validate_intervals([_row(0), _row(0)])["ok"]
    assert not validate_intervals([_row(0), _row(2)])["ok"]


def test_validate_split_must_match_distance_and_time():
    ok = _row(0, work_duration_s=105.0, avg_split_s=105.0)
    bad = _row(0, work_duration_s=105.0, avg_split_s=80.0)
    assert validate_intervals([ok])["ok"]
    assert not validate_intervals([bad])["ok"]


def test_validate_incomplete_interval_is_ok():
    assert validate_intervals([_row(0)])["ok"]  # target only; nothing achieved yet


def test_summary_totals_separate_work_and_rest():
    rows = [_row(0, work_duration_s=100, rest_duration_s=60), _row(1, work_duration_s=110, rest_duration_s=60), _row(2, work_duration_s=120)]
    s = summarize_intervals(rows)
    assert s["work_distance_m"] == 1500 and s["work_duration_s"] == 330 and s["rest_duration_s"] == 120
    assert s["total_duration_s"] == 450


def test_summary_split_is_total_time_over_total_distance_not_mean_of_splits():
    rows = [
        {"position": 0, "target_type": "distance", "work_distance_m": 500.0, "work_duration_s": 100.0},
        {"position": 1, "target_type": "distance", "work_distance_m": 2000.0, "work_duration_s": 500.0},
    ]
    s = summarize_intervals(rows)
    # splits are 100.0 and 125.0 -> a naive mean is 112.5; the real pace is 600s/2500m*500 = 120.0
    assert s["avg_split_s"] == pytest.approx(120.0)


def test_summary_weights_power_by_time_and_skips_missing_metrics():
    rows = [
        {"position": 0, "target_type": "time", "work_duration_s": 60.0, "avg_watts": 300.0, "avg_hr": 160.0},
        {"position": 1, "target_type": "time", "work_duration_s": 180.0, "avg_watts": 200.0},
        {"position": 2, "target_type": "time", "work_duration_s": 60.0},
    ]
    s = summarize_intervals(rows)
    assert s["avg_watts"] == pytest.approx((300 * 60 + 200 * 180) / 240)  # not (300+200)/2
    assert s["avg_hr"] == pytest.approx(160.0)  # the rows with no HR don't drag it toward 0
    assert s["avg_rate"] is None and s["calories"] is None


def test_summary_max_hr_and_calories():
    rows = [
        {"position": 0, "target_type": "time", "work_duration_s": 60.0, "max_hr": 181.0, "calories": 20.0},
        {"position": 1, "target_type": "time", "work_duration_s": 60.0, "max_hr": 175.0, "calories": 22.0},
    ]
    s = summarize_intervals(rows)
    assert s["max_hr"] == 181.0 and s["calories"] == 42.0


def test_summary_empty():
    s = summarize_intervals([])
    assert s["count"] == 0 and s["work_distance_m"] is None and s["avg_split_s"] is None


def test_derived_split():
    assert derived_split_s({"work_distance_m": 500, "work_duration_s": 105}) == pytest.approx(105.0)
    assert derived_split_s({"work_distance_m": 500}) is None
    assert derived_split_s({"avg_split_s": 99.0, "work_distance_m": 500, "work_duration_s": 105}) == 99.0


def test_signature_uniform_and_variable():
    assert interval_signature(expand_repeat(4, work_distance_m=500, rest_duration_s=60)) == "4x500m/r60"
    assert interval_signature(expand_repeat(8, work_duration_s=60, rest_duration_s=60)) == "8x60s/r60"
    ladder = [_row(0, work_distance_m=500, rest_duration_s=60), _row(1, work_distance_m=1000, rest_duration_s=120), _row(2, work_distance_m=500)]
    assert interval_signature(ladder) == "500m/r60+1000m/r120+500m/r0"
    assert interval_signature([]) is None
