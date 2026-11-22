"""Session 33: the pure rules for combining workouts (catch/analytics/activity_merge.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from catch.analytics.activity_merge import Span, check_compatible, cluster, overlaps, span_of, sum_known, weighted_mean

T0 = datetime(2026, 11, 20, 7, tzinfo=timezone.utc)


def _span(key, start_min, minutes):
    return Span(key, T0 + timedelta(minutes=start_min), T0 + timedelta(minutes=start_min + minutes))


def _item(i, start_min, minutes, **kw):
    return {"id": i, "sport_family": "rowing", "category": "erg", "start": T0 + timedelta(minutes=start_min), "duration": minutes * 60.0, **kw}


def test_sequential_recordings_are_separate_groups_and_overlapping_ones_one():
    groups = cluster([_span(1, 0, 30), _span(2, 35, 20), _span(3, 36, 18)])
    assert [[s.key for s in g] for g in groups] == [[1], [2, 3]]


def test_touching_end_to_start_is_not_an_overlap():
    assert len(cluster([_span(1, 0, 30), _span(2, 30, 10)])) == 2


def test_weighted_mean_is_by_duration_never_the_mean_of_means():
    # 40 min at 140 and 10 min at 170: 146, not (140 + 170) / 2 = 155.
    assert weighted_mean([(140, 2400), (170, 600)]) == pytest.approx(146)
    assert weighted_mean([(None, 600), (150, 0)]) is None


def test_missing_values_are_summed_as_known_and_flagged():
    assert sum_known([5000, None, 2000]) == (7000, True)
    assert sum_known([None, None]) == (None, True)
    assert sum_known([1, 2]) == (3, False)


def test_overlaps_report_seconds():
    assert overlaps([_span(1, 0, 30), _span(2, 25, 10)]) == [{"a": 1, "b": 2, "seconds": 300}]


def test_compatible_sequential_parts():
    assert check_compatible([_item(1, 0, 30), _item(2, 40, 20)]) == []


@pytest.mark.parametrize(
    ("items", "fragment"),
    [
        ([_item(1, 0, 30)], "at least two"),
        ([_item(1, 0, 30), _item(2, 40, 20, sport_family="cycling")], "different sports"),
        ([_item(1, 0, 30, sport_family="strength"), _item(2, 40, 20, sport_family="strength")], "Strength"),
        ([_item(1, 0, 30), _item(2, 40, 20, category="on_water")], "erg session and an on-water"),
        ([_item(1, 0, 30), _item(2, 200, 20)], "gap of more than"),
        ([_item(1, 0, 200), _item(2, 210, 200)], "more than 6 hours"),
        ([_item(1, 0, 30, test_type="2000m"), _item(2, 40, 20, test_type="2000m")], "confirmed test"),
        ([_item(1, 0, 30, published=True), _item(2, 40, 20, published=True)], "leaderboard"),
        ([_item(1, 0, 60), _item(2, 5, 10), _item(3, 30, 10)], "pieces within one session"),
        ([_item(i, i * 20, 10) for i in range(11)], "at most 10"),
        ([_item(1, 0, 30), {**_item(2, 40, 20), "start": None}], "no start time"),
    ],
)
def test_incompatible_selections_say_why(items, fragment):
    reasons = check_compatible(items)
    assert any(fragment in r for r in reasons), reasons


def test_true_duplicates_inside_a_selection_are_fine():
    # A watch and the erg recording the same 30 minutes, then a second part — mutually overlapping inside the group.
    assert check_compatible([_item(1, 0, 30), _item(2, 1, 29), _item(3, 40, 20)]) == []


def test_span_of_needs_a_start():
    assert span_of(1, None, 60) is None
    assert span_of(1, T0, None) == Span(1, T0, T0)
