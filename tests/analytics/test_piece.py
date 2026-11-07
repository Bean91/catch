from __future__ import annotations

import json
from pathlib import Path

import pytest

from catch.analytics.piece import (
    aggregate_from_splits,
    default_splits,
    find_best_window,
    parse_splits_paste,
    validate_splits,
    watts_for_split,
)

# The task's own example: 6:32.4 total, splits 1:36.8, 1:38.9, 1:39.0, 1:37.7 — sums exactly.
_TASK_2K_SPLITS_S = [96.8, 98.9, 99.0, 97.7]
_TASK_2K_TOTAL_S = 392.4


def _rows(splits_s, distances=(500, 1000, 1500, 2000)):
    return [{"split_index": i + 1, "distance_m": float(d), "split_s": s, "rate": 32.0, "watts": None, "hr": None} for i, (d, s) in enumerate(zip(distances, splits_s))]


def test_default_splits_2000m_is_four_rows_of_500():
    rows = default_splits("2000m")
    assert [r["distance_m"] for r in rows] == [500.0, 1000.0, 1500.0, 2000.0]
    assert all(r["split_s"] is None for r in rows)


def test_default_splits_30min_r20_is_duration_based():
    rows = default_splits("30min_r20")
    assert len(rows) == 6  # 1800s / 300s default rows
    assert all(r["distance_m"] is None for r in rows)


def test_default_splits_custom_uses_supplied_distance():
    rows = default_splits("custom", distance_m=1500.0)
    assert len(rows) == 3


def test_validate_splits_accepts_the_tasks_own_exact_example():
    rows = _rows(_TASK_2K_SPLITS_S)
    result = validate_splits(rows, total_distance_m=2000.0, total_duration_s=_TASK_2K_TOTAL_S)
    assert result == {"ok": True, "issues": []}


def test_validate_splits_flags_a_total_time_mismatch():
    rows = _rows([96.8, 98.9, 99.0, 90.0])  # last split way off, sum no longer matches
    result = validate_splits(rows, total_distance_m=2000.0, total_duration_s=_TASK_2K_TOTAL_S)
    assert not result["ok"]
    assert any(i["field"] == "total_time" for i in result["issues"])


def test_validate_splits_flags_a_distance_mismatch():
    rows = _rows(_TASK_2K_SPLITS_S, distances=(500, 1000, 1500, 1950))
    result = validate_splits(rows, total_distance_m=2000.0, total_duration_s=_TASK_2K_TOTAL_S)
    assert any(i["field"] == "total_distance" for i in result["issues"])


def test_validate_splits_flags_an_implausible_rate():
    rows = _rows(_TASK_2K_SPLITS_S)
    rows[0]["rate"] = 95.0
    result = validate_splits(rows, total_distance_m=2000.0, total_duration_s=_TASK_2K_TOTAL_S)
    assert any(i["split_index"] == 1 and i["field"] == "rate" for i in result["issues"])


def test_validate_splits_flags_watts_that_disagree_with_the_split():
    rows = _rows(_TASK_2K_SPLITS_S)
    rows[0]["watts"] = watts_for_split(96.8) + 50  # way off from what the split implies
    result = validate_splits(rows, total_distance_m=2000.0, total_duration_s=_TASK_2K_TOTAL_S)
    assert any(i["split_index"] == 1 and i["field"] == "watts" for i in result["issues"])


def test_validate_splits_accepts_watts_within_tolerance_of_the_split():
    rows = _rows(_TASK_2K_SPLITS_S)
    rows[0]["watts"] = round(watts_for_split(96.8))  # PM5's own integer rounding
    result = validate_splits(rows, total_distance_m=2000.0, total_duration_s=_TASK_2K_TOTAL_S)
    assert not any(i["field"] == "watts" for i in result["issues"])


def test_validate_splits_skips_checks_with_insufficient_data():
    rows = default_splits("2000m")  # nothing filled in yet
    result = validate_splits(rows, total_distance_m=2000.0, total_duration_s=None)
    assert result == {"ok": True, "issues": []}


def test_aggregate_from_splits():
    rows = _rows(_TASK_2K_SPLITS_S)
    agg = aggregate_from_splits(rows)
    assert agg["duration_s"] == pytest.approx(_TASK_2K_TOTAL_S)
    assert agg["distance_m"] == 2000.0
    assert agg["avg_split_s"] == pytest.approx(sum(_TASK_2K_SPLITS_S) / 4)


def test_parse_splits_paste_matches_the_tasks_own_example():
    text = "1:36.8 32 / 1:38.9 30 / 1:39.0 31 / 1:37.7 32"
    rows = parse_splits_paste(text)
    assert [r["split_s"] for r in rows] == pytest.approx(_TASK_2K_SPLITS_S)
    assert [r["rate"] for r in rows] == [32.0, 30.0, 31.0, 32.0]


_PASTE_VECTORS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "pieces" / "paste_vectors.json"
_PASTE_VECTORS = json.loads(_PASTE_VECTORS_PATH.read_text())


@pytest.mark.parametrize("vector", _PASTE_VECTORS, ids=[v["name"] for v in _PASTE_VECTORS])
def test_parse_splits_paste_matches_shared_vectors(vector):
    """Shared with web/src/lib/pieceSplits.test.ts — the exact same input/output pairs, so
    the Python and TS paste parsers can't silently drift from each other."""
    rows = parse_splits_paste(vector["input"])
    assert [r["split_s"] for r in rows] == pytest.approx(vector["splits"])
    assert [r["rate"] for r in rows] == vector["rates"]


def test_parse_splits_paste_handles_newlines_and_missing_rate():
    rows = parse_splits_paste("1:36.8\n1:38.9")
    assert [r["split_s"] for r in rows] == [96.8, 98.9]
    assert rows[0]["rate"] is None


def test_parse_splits_paste_raises_with_the_bad_tokens_position():
    with pytest.raises(ValueError, match="split 2"):
        parse_splits_paste("1:36.8 32 / garbage 30")


def test_find_best_window_locates_a_hr_rise():
    # 30s baseline ~120, 30s ramp up to ~170, hold, then cool down — a 20s window should land
    # on the held-high stretch, not biased all the way to the very end.
    hr = [120.0] * 30 + [120.0 + i * 1.6 for i in range(30)] + [170.0] * 20 + [140.0] * 30
    start = find_best_window(hr, window_len_s=20)
    assert start is not None
    assert 58 <= start <= 80


def test_find_best_window_returns_none_when_recording_is_too_short():
    assert find_best_window([120.0] * 10, window_len_s=20) is None


def test_find_best_window_skips_missing_samples():
    hr = [None] * 10 + [150.0] * 10 + [None] * 10
    start = find_best_window(hr, window_len_s=10)
    assert start == 10
