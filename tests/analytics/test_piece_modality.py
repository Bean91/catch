"""Session 33: rowing erg vs bike pieces — the pure math (shared vectors with web/src/lib/pieceSplits.test.ts)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from catch.analytics.leaderboards import eligible_board
from catch.analytics.piece import aggregate_from_splits, check_modality, default_splits, totals_only_splits, validate_splits
from catch.analytics.piece_intervals import summarize_intervals, validate_intervals

VECTORS = json.loads((Path(__file__).parents[1] / "fixtures" / "pieces" / "split_unit_vectors.json").read_text())


@pytest.mark.parametrize("case", VECTORS["aggregate"], ids=lambda c: c["name"])
def test_average_split_is_per_the_machines_unit(case):
    assert aggregate_from_splits(case["rows"], case["modality"])["avg_split_s"] == pytest.approx(case["avg_split_s"])


@pytest.mark.parametrize("case", VECTORS["validate"], ids=lambda c: c["name"])
def test_validation_per_modality(case):
    issues = validate_splits(case["rows"], None, None, case["modality"])["issues"]
    assert sorted(i["field"] for i in issues) == sorted(case["fields"])


@pytest.mark.parametrize("case", VECTORS["default_rows"], ids=lambda c: f"{c['modality']} {c['piece_type']}")
def test_template_rows_follow_the_split_unit(case):
    assert [r["distance_m"] for r in default_splits(case["piece_type"], modality=case["modality"])] == case["distances"]


def test_rowing_is_the_default_so_old_callers_are_unchanged():
    rows = VECTORS["aggregate"][0]["rows"]
    assert aggregate_from_splits(rows)["avg_split_s"] == aggregate_from_splits(rows, "rowing_erg")["avg_split_s"]


def test_rate_capped_rowing_test_is_not_a_bike_type():
    assert check_modality("bike", "30min_r20") is not None
    assert check_modality("bike", "2000m") is None
    assert check_modality("rowing_erg", "30min_r20") is None
    assert check_modality("skierg", "2000m") is not None


def test_totals_only_row():
    assert totals_only_splits(None, None) == []
    assert totals_only_splits(5000, 1200.0, 26) == [{"split_index": 1, "distance_m": 5000, "split_s": 1200.0, "rate": 26, "watts": None, "hr": None}]


def test_bike_intervals_use_1000m_splits_and_cadence():
    rows = [
        {"position": 0, "target_type": "distance", "work_distance_m": 1000, "work_duration_s": 100, "avg_rate": 90},
        {"position": 1, "target_type": "distance", "work_distance_m": 1000, "work_duration_s": 104, "avg_rate": 92},
    ]
    assert summarize_intervals(rows, "bike")["avg_split_s"] == pytest.approx(102.0)
    assert summarize_intervals(rows, "rowing_erg")["avg_split_s"] == pytest.approx(51.0)
    assert validate_intervals(rows, "bike")["ok"]
    assert [i["field"] for i in validate_intervals(rows, "rowing_erg")["issues"]] == ["avg_rate", "avg_rate"]


def test_a_bike_piece_is_never_eligible_for_a_rowing_board():
    assert eligible_board(distance_m=2000, duration_s=400.0, is_piece=True) is not None
    assert eligible_board(distance_m=2000, duration_s=400.0, is_piece=True, modality="bike") is None
